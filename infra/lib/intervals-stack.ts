import { Duration, Stack, StackProps } from 'aws-cdk-lib';
import * as apigw from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
import { PythonFunction } from './python-function';

export interface IntervalsStackProps extends StackProps {
  readonly athleteId: string;
  readonly intervalsTable: dynamodb.ITable;
  readonly httpApi: apigw.HttpApi;
  readonly authorizer: apigw.IHttpRouteAuthorizer;
  /** First day fetched when the table is empty (YYYY-MM-DD). */
  readonly backfillStartDate: string;
}

/**
 * Intervals.icu ingestion:
 *   EventBridge (6h) / POST /intervals/sync -> intervals-sync -> IntervalsDaily
 *
 * The API key lives in a secret created by hand (documentation/labs/03-intervals.md).
 * Until it exists the sync logs a warning and does nothing.
 */
export class IntervalsStack extends Stack {
  constructor(scope: Construct, id: string, props: IntervalsStackProps) {
    super(scope, id, props);

    const secret = secretsmanager.Secret.fromSecretNameV2(this, 'IntervalsSecret', 'intervals/api');

    const syncFn = new PythonFunction(this, 'Sync', {
      functionName: 'intervals-sync',
      handlerModule: 'intervals/sync/handler',
      description: 'Copies Intervals.icu daily wellness and fitness records into IntervalsDaily',
      timeout: Duration.seconds(120),
      environment: {
        ATHLETE_ID: props.athleteId,
        ATHLETE_TIMEZONE: 'Europe/London',
        INTERVALS_SECRET_ID: secret.secretName,
        INTERVALS_TABLE: props.intervalsTable.tableName,
        BACKFILL_START_DATE: props.backfillStartDate,
      },
      reservedConcurrentExecutions: 1,
    });
    secret.grantRead(syncFn);
    props.intervalsTable.grantReadWriteData(syncFn);

    new events.Rule(this, 'SyncSchedule', {
      ruleName: 'intervals-sync-every-6h',
      schedule: events.Schedule.rate(Duration.hours(6)),
      targets: [new targets.LambdaFunction(syncFn)],
    });

    new apigw.HttpRoute(this, 'SyncRoute', {
      httpApi: props.httpApi,
      routeKey: apigw.HttpRouteKey.with('/intervals/sync', apigw.HttpMethod.POST),
      integration: new HttpLambdaIntegration('SyncIntegration', syncFn),
      authorizer: props.authorizer,
    });
  }
}
