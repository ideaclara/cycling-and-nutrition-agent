import { CfnOutput, Stack, StackProps } from 'aws-cdk-lib';
import * as apigw from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';
import { PythonFunction } from './python-function';

export interface CoachApiStackProps extends StackProps {
  readonly athleteId: string;
  readonly withingsUserId: string;
  readonly dailyLogTable: dynamodb.ITable;
  readonly activitiesTable: dynamodb.ITable;
  readonly withingsTable: dynamodb.ITable;
  readonly httpApi: apigw.HttpApi;
  readonly authorizer: apigw.IHttpRouteAuthorizer;
}

/**
 * Daily-log CRUD for the manual-entry form, plus the three Lambdas that a
 * Bedrock Agent's action groups call.
 *
 * Deliberately NOT here: the resource-based policy that lets Bedrock invoke the
 * action Lambdas. You add that by hand in Module C so you see how agents get
 * permission to call your code.
 */
export class CoachApiStack extends Stack {
  constructor(scope: Construct, id: string, props: CoachApiStackProps) {
    super(scope, id, props);

    const baseEnv = {
      ATHLETE_ID: props.athleteId,
      ATHLETE_TIMEZONE: 'Europe/London',
      DAILY_LOG_TABLE: props.dailyLogTable.tableName,
    };

    const dailyLogFn = new PythonFunction(this, 'DailyLog', {
      functionName: 'coach-daily-log',
      handlerModule: 'coach/daily_log/handler',
      description: 'Daily fitness log API (manual entry form)',
      environment: baseEnv,
    });
    props.dailyLogTable.grantReadWriteData(dailyLogFn);

    const integration = new HttpLambdaIntegration('DailyLogIntegration', dailyLogFn);
    const routes: [string, apigw.HttpMethod][] = [
      ['/daily-log', apigw.HttpMethod.GET],
      ['/daily-log/schema', apigw.HttpMethod.GET],
      ['/daily-log/{date}', apigw.HttpMethod.GET],
      ['/daily-log/{date}', apigw.HttpMethod.PUT],
    ];
    routes.forEach(([path, method]) => {
      new apigw.HttpRoute(this, `Route${method}${path.replace(/[^A-Za-z]/g, '')}`, {
        httpApi: props.httpApi,
        routeKey: apigw.HttpRouteKey.with(path, method),
        integration,
        authorizer: props.authorizer,
      });
    });

    const getDailyMetricsFn = new PythonFunction(this, 'GetDailyMetrics', {
      functionName: 'coach-action-get-daily-metrics',
      handlerModule: 'coach/actions/get_daily_metrics/handler',
      description: 'Agent action: consolidated daily metrics (log + Withings + Strava)',
      environment: {
        ...baseEnv,
        ACTIVITIES_TABLE: props.activitiesTable.tableName,
        WITHINGS_TABLE: props.withingsTable.tableName,
        WITHINGS_USER_ID: props.withingsUserId,
      },
    });
    props.dailyLogTable.grantReadData(getDailyMetricsFn);
    props.activitiesTable.grantReadData(getDailyMetricsFn);
    props.withingsTable.grantReadData(getDailyMetricsFn);

    const logDqsFn = new PythonFunction(this, 'LogDqsEntry', {
      functionName: 'coach-action-log-dqs-entry',
      handlerModule: 'coach/actions/log_dqs_entry/handler',
      description: 'Agent action: score food items with the Diet Quality Score',
      environment: baseEnv,
    });
    props.dailyLogTable.grantReadWriteData(logDqsFn);

    const rampRateFn = new PythonFunction(this, 'CalculateRampRate', {
      functionName: 'coach-action-calculate-ramp-rate',
      handlerModule: 'coach/actions/calculate_ramp_rate/handler',
      description: 'Agent action: CTL ramp rate and ATL/TSB trend',
      environment: baseEnv,
    });
    props.dailyLogTable.grantReadData(rampRateFn);

    new CfnOutput(this, 'GetDailyMetricsArn', { value: getDailyMetricsFn.functionArn });
    new CfnOutput(this, 'LogDqsEntryArn', { value: logDqsFn.functionArn });
    new CfnOutput(this, 'CalculateRampRateArn', { value: rampRateFn.functionArn });
  }
}
