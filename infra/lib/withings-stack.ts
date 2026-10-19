import { Duration, Stack, StackProps } from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import { Construct } from 'constructs';
import { PythonFunction } from './python-function';

export interface WithingsStackProps extends StackProps {
  readonly withingsTable: dynamodb.ITable;
  /** Name of the secret copied by hand from eu-west-2. */
  readonly secretName: string;
}

/**
 * Withings scale ingestion, ported from eu-west-2:
 *   EventBridge (hourly) -> Step Functions [RefreshToken -> SyncMeasures] -> WithingsTelemetry
 *
 * The AppConfig-driven dispatcher of the original is replaced by a plain
 * schedule, since only the `measures` endpoint is needed here.
 */
export class WithingsStack extends Stack {
  constructor(scope: Construct, id: string, props: WithingsStackProps) {
    super(scope, id, props);

    const secret = secretsmanager.Secret.fromSecretNameV2(this, 'WithingsSecret', props.secretName);

    const tokenFn = new PythonFunction(this, 'TokenRefresher', {
      functionName: 'withings-token-refresher',
      handlerModule: 'withings/token_refresher/handler',
      description: 'Returns a valid Withings access token, refreshing if near expiry',
      environment: { WITHINGS_SECRET_ID: props.secretName },
    });
    secret.grantRead(tokenFn);
    secret.grantWrite(tokenFn);

    const syncFn = new PythonFunction(this, 'SyncMeasures', {
      functionName: 'withings-sync-measures',
      handlerModule: 'withings/sync_measures/handler',
      description: 'Fetches Withings measure groups and upserts consolidated sessions',
      timeout: Duration.seconds(60),
      environment: { WITHINGS_TABLE: props.withingsTable.tableName },
    });
    props.withingsTable.grantWriteData(syncFn);

    const lambdaRetry = {
      errors: ['Lambda.ClientExecutionTimeoutException', 'Lambda.ServiceException', 'Lambda.AWSLambdaException', 'Lambda.SdkClientException'],
      interval: Duration.seconds(2),
      maxAttempts: 6,
      backoffRate: 2,
    };

    const refresh = new tasks.LambdaInvoke(this, 'RefreshToken', {
      lambdaFunction: tokenFn,
      payload: sfn.TaskInput.fromObject({ 'secret_name.$': '$.secret_name' }),
      resultSelector: { 'access_token.$': '$.Payload.access_token', 'userid.$': '$.Payload.userid' },
      resultPath: '$.auth',
      retryOnServiceExceptions: false,
    }).addRetry(lambdaRetry);

    const sync = new tasks.LambdaInvoke(this, 'SyncMeasuresTask', {
      lambdaFunction: syncFn,
      payload: sfn.TaskInput.fromObject({
        'endpoint_config.$': '$.endpoint_config',
        'access_token.$': '$.auth.access_token',
        'userid.$': '$.auth.userid',
      }),
      outputPath: '$.Payload',
      retryOnServiceExceptions: false,
    }).addRetry(lambdaRetry);

    const stateMachine = new sfn.StateMachine(this, 'Pipeline', {
      stateMachineName: 'withings-ingestion',
      definitionBody: sfn.DefinitionBody.fromChainable(refresh.next(sync)),
      timeout: Duration.minutes(5),
    });

    // Created DISABLED: enable it only after the eu-west-2 schedule is turned off,
    // because both pipelines would rotate the same refresh token.
    new events.Rule(this, 'HourlySchedule', {
      ruleName: 'withings-sync-hourly',
      enabled: false,
      schedule: events.Schedule.rate(Duration.hours(1)),
      targets: [
        new targets.SfnStateMachine(stateMachine, {
          input: events.RuleTargetInput.fromObject({
            secret_name: props.secretName,
            endpoint_config: { lookback_days: 30 },
          }),
        }),
      ],
    });
  }
}
