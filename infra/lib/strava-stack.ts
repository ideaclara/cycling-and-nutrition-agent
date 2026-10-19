import { Duration, Stack, StackProps } from 'aws-cdk-lib';
import * as apigw from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';
import { PythonFunction } from './python-function';

export interface StravaStackProps extends StackProps {
  readonly activitiesTable: dynamodb.ITable;
  readonly dataBucket: s3.IBucket;
  readonly httpApi: apigw.HttpApi;
  readonly authorizer: apigw.IHttpRouteAuthorizer;
  /** Epoch seconds for the first backfill (2026-01-01T00:00:00Z). */
  readonly backfillStartEpoch: number;
}

/**
 * Strava activity ingestion:
 *   EventBridge (6h) / POST /strava/sync -> list_activities -> SQS -> fetch_activity_worker -> DynamoDB (+S3)
 * plus the OAuth endpoints that store tokens in Secrets Manager.
 */
export class StravaStack extends Stack {
  constructor(scope: Construct, id: string, props: StravaStackProps) {
    super(scope, id, props);

    // Created by hand, not by CloudFormation (documentation/labs/01-strava.md), so
    // a stack update or teardown can never overwrite or delete live OAuth tokens.
    const secret = secretsmanager.Secret.fromSecretNameV2(this, 'StravaOAuthSecret', 'strava/oauth');

    const dlq = new sqs.Queue(this, 'FetchDlq', {
      queueName: 'strava-activity-fetch-dlq',
      retentionPeriod: Duration.days(14),
    });
    const queue = new sqs.Queue(this, 'FetchQueue', {
      queueName: 'strava-activity-fetch-queue',
      visibilityTimeout: Duration.seconds(90),
      deadLetterQueue: { queue: dlq, maxReceiveCount: 5 },
    });

    const common = {
      STRAVA_SECRET_ID: secret.secretName,
      ACTIVITIES_TABLE: props.activitiesTable.tableName,
    };

    const authFn = new PythonFunction(this, 'AuthCallback', {
      functionName: 'strava-auth-callback',
      handlerModule: 'strava/auth_callback/handler',
      description: 'Strava OAuth authorize redirect + callback (tokens -> Secrets Manager)',
      environment: common,
    });
    secret.grantRead(authFn);
    secret.grantWrite(authFn);

    const listFn = new PythonFunction(this, 'ListActivities', {
      functionName: 'strava-list-activities',
      handlerModule: 'strava/list_activities/handler',
      description: 'Lists new Strava activities and queues each for a detail fetch',
      timeout: Duration.seconds(60),
      environment: {
        ...common,
        FETCH_QUEUE_URL: queue.queueUrl,
        BACKFILL_START_EPOCH: String(props.backfillStartEpoch),
      },
      // One sync at a time: the schedule and a manual POST can't overlap.
      reservedConcurrentExecutions: 1,
    });
    secret.grantRead(listFn);
    secret.grantWrite(listFn);
    props.activitiesTable.grantReadData(listFn);
    queue.grantSendMessages(listFn);

    const workerFn = new PythonFunction(this, 'FetchActivityWorker', {
      functionName: 'strava-fetch-activity-worker',
      handlerModule: 'strava/fetch_activity_worker/handler',
      description: 'Fetches one activity (include_all_efforts) and stores it',
      timeout: Duration.seconds(60),
      memorySize: 512,
      environment: {
        ...common,
        FETCH_QUEUE_URL: queue.queueUrl,
        DATA_BUCKET: props.dataBucket.bucketName,
      },
    });
    secret.grantRead(workerFn);
    secret.grantWrite(workerFn);
    props.activitiesTable.grantReadWriteData(workerFn);
    props.dataBucket.grantPut(workerFn, 'strava/activities/*');
    queue.grant(workerFn, 'sqs:ChangeMessageVisibility');
    // maxConcurrency 2 is the SQS event source minimum; each fetch is one Strava call.
    workerFn.addEventSource(new SqsEventSource(queue, { batchSize: 1, maxConcurrency: 2 }));

    new events.Rule(this, 'SyncSchedule', {
      ruleName: 'strava-sync-every-6h',
      schedule: events.Schedule.rate(Duration.hours(6)),
      targets: [new targets.LambdaFunction(listFn)],
    });

    // OAuth routes must be public (Strava's redirect carries no JWT); the
    // callback is protected by the one-time `state` nonce instead. Routes are
    // created in this stack (not via httpApi.addRoutes) to avoid a cross-stack cycle.
    const route = (id: string, path: string, method: apigw.HttpMethod, fn: PythonFunction, secured: boolean) =>
      new apigw.HttpRoute(this, id, {
        httpApi: props.httpApi,
        routeKey: apigw.HttpRouteKey.with(path, method),
        integration: new HttpLambdaIntegration(`${id}Integration`, fn),
        authorizer: secured ? props.authorizer : undefined,
      });
    route('AuthorizeRoute', '/strava/authorize', apigw.HttpMethod.GET, authFn, false);
    route('CallbackRoute', '/strava/callback', apigw.HttpMethod.GET, authFn, false);
    route('SyncRoute', '/strava/sync', apigw.HttpMethod.POST, listFn, true);
  }
}
