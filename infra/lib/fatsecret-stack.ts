import { Duration, Stack, StackProps } from 'aws-cdk-lib';
import * as apigw from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
import { PythonFunction } from './python-function';

export interface FatSecretStackProps extends StackProps {
  readonly athleteId: string;
  readonly fatSecretTable: dynamodb.ITable;
  readonly httpApi: apigw.HttpApi;
  readonly authorizer: apigw.IHttpRouteAuthorizer;
  /** First day fetched when the table is empty (YYYY-MM-DD). */
  readonly backfillStartDate: string;
}

/**
 * FatSecret food diary ingestion:
 *   EventBridge (6h) / POST /fatsecret/sync -> fatsecret-sync -> FatSecretDaily
 *
 * The OAuth 1.0 keys live in a secret created by hand, and the user's access
 * token is added by scripts/fatsecret_authorize.py (documentation/labs/04-fatsecret.md).
 * Until both exist the sync logs a warning and does nothing.
 */
export class FatSecretStack extends Stack {
  constructor(scope: Construct, id: string, props: FatSecretStackProps) {
    super(scope, id, props);

    const secret = secretsmanager.Secret.fromSecretNameV2(this, 'FatSecretSecret', 'fatsecret/oauth');

    const syncFn = new PythonFunction(this, 'Sync', {
      functionName: 'fatsecret-sync',
      handlerModule: 'fatsecret/sync/handler',
      description: 'Copies the FatSecret food diary into FatSecretDaily',
      timeout: Duration.seconds(120),
      environment: {
        ATHLETE_ID: props.athleteId,
        ATHLETE_TIMEZONE: 'Europe/London',
        FATSECRET_SECRET_ID: secret.secretName,
        FATSECRET_TABLE: props.fatSecretTable.tableName,
        BACKFILL_START_DATE: props.backfillStartDate,
      },
      reservedConcurrentExecutions: 1,
    });
    secret.grantRead(syncFn);
    props.fatSecretTable.grantReadWriteData(syncFn);

    new events.Rule(this, 'SyncSchedule', {
      ruleName: 'fatsecret-sync-every-6h',
      schedule: events.Schedule.rate(Duration.hours(6)),
      targets: [new targets.LambdaFunction(syncFn)],
    });

    new apigw.HttpRoute(this, 'SyncRoute', {
      httpApi: props.httpApi,
      routeKey: apigw.HttpRouteKey.with('/fatsecret/sync', apigw.HttpMethod.POST),
      integration: new HttpLambdaIntegration('SyncIntegration', syncFn),
      authorizer: props.authorizer,
    });
  }
}
