import { CfnOutput, Duration, Stack, StackProps, TimeZone } from 'aws-cdk-lib';
import * as apigw from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as scheduler from 'aws-cdk-lib/aws-scheduler';
import * as schedulerTargets from 'aws-cdk-lib/aws-scheduler-targets';
import { Construct } from 'constructs';
import { PythonFunction } from './python-function';

export interface CoachApiStackProps extends StackProps {
  readonly athleteId: string;
  readonly withingsUserId: string;
  readonly dailyLogTable: dynamodb.ITable;
  readonly activitiesTable: dynamodb.ITable;
  readonly withingsTable: dynamodb.ITable;
  readonly readingsTable: dynamodb.ITable;
  readonly intervalsTable: dynamodb.ITable;
  readonly intervalsActivitiesTable: dynamodb.ITable;
  readonly fatSecretTable: dynamodb.ITable;
  readonly adviceTable: dynamodb.ITable;
  readonly chatTable: dynamodb.ITable;
  /** Set after Module C (Bedrock Agent) and Module G (AgentCore); chat returns 503 for a backend until then. */
  readonly chatBackends: { agentId?: string; agentAliasId?: string; agentRuntimeArn?: string };
  /** Inference profile ID for the daily advice (the `flow` role in config/models.json). */
  readonly adviceModelId: string;
  /** Guardrail built by hand in Module B; advice runs without one until it's set. */
  readonly guardrail?: { id: string; version: string };
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
    const readEnv = {
      ...baseEnv,
      INTERVALS_TABLE: props.intervalsTable.tableName,
      INTERVALS_ACTIVITIES_TABLE: props.intervalsActivitiesTable.tableName,
      FATSECRET_TABLE: props.fatSecretTable.tableName,
      READINGS_TABLE: props.readingsTable.tableName,
    };

    const dailyLogFn = new PythonFunction(this, 'DailyLog', {
      functionName: 'coach-daily-log',
      handlerModule: 'coach/daily_log/handler',
      description: 'Daily fitness log API (manual entry form)',
      environment: readEnv,
    });
    props.dailyLogTable.grantReadWriteData(dailyLogFn);
    props.intervalsTable.grantReadData(dailyLogFn);
    props.fatSecretTable.grantReadData(dailyLogFn);

    const integration = new HttpLambdaIntegration('DailyLogIntegration', dailyLogFn);
    const routes: [string, apigw.HttpMethod][] = [
      ['/daily-log', apigw.HttpMethod.GET],
      ['/daily-log/schema', apigw.HttpMethod.GET],
      ['/daily-log/{date}', apigw.HttpMethod.GET],
      ['/daily-log/{date}', apigw.HttpMethod.PUT],
    ];
    this.addRoutes(props, integration, routes);

    const readingsFn = new PythonFunction(this, 'Readings', {
      functionName: 'coach-readings',
      handlerModule: 'coach/readings/handler',
      description: 'Manual blood pressure and temperature readings API',
      environment: readEnv,
    });
    props.readingsTable.grantReadWriteData(readingsFn);
    this.addRoutes(props, new HttpLambdaIntegration('ReadingsIntegration', readingsFn), [
      ['/readings', apigw.HttpMethod.GET],
      ['/readings', apigw.HttpMethod.POST],
      ['/readings/schema', apigw.HttpMethod.GET],
      ['/readings/{type}/{ts}', apigw.HttpMethod.DELETE],
    ]);

    const getDailyMetricsFn = new PythonFunction(this, 'GetDailyMetrics', {
      functionName: 'coach-action-get-daily-metrics',
      handlerModule: 'coach/actions/get_daily_metrics/handler',
      description: 'Agent action: consolidated daily metrics (log + Withings + Strava)',
      environment: {
        ...readEnv,
        ACTIVITIES_TABLE: props.activitiesTable.tableName,
        WITHINGS_TABLE: props.withingsTable.tableName,
        WITHINGS_USER_ID: props.withingsUserId,
      },
    });
    props.dailyLogTable.grantReadData(getDailyMetricsFn);
    props.activitiesTable.grantReadData(getDailyMetricsFn);
    props.withingsTable.grantReadData(getDailyMetricsFn);
    props.intervalsTable.grantReadData(getDailyMetricsFn);
    props.intervalsActivitiesTable.grantReadData(getDailyMetricsFn);
    props.readingsTable.grantReadData(getDailyMetricsFn);
    props.fatSecretTable.grantReadData(getDailyMetricsFn);

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
      environment: readEnv,
    });
    props.dailyLogTable.grantReadData(rampRateFn);
    props.intervalsTable.grantReadData(rampRateFn);

    const allSources = (fn: PythonFunction) => {
      [
        props.dailyLogTable,
        props.intervalsTable,
        props.intervalsActivitiesTable,
        props.fatSecretTable,
        props.readingsTable,
        props.withingsTable,
        props.activitiesTable,
      ].forEach(
        (t) => t.grantReadData(fn),
      );
    };
    const sourcesEnv = {
      ...readEnv,
      ACTIVITIES_TABLE: props.activitiesTable.tableName,
      WITHINGS_TABLE: props.withingsTable.tableName,
      WITHINGS_USER_ID: props.withingsUserId,
    };

    const analysisFn = new PythonFunction(this, 'Analysis', {
      functionName: 'coach-analysis',
      handlerModule: 'coach/analysis/handler',
      description: 'Per-day series from every source for the analysis page',
      memorySize: 512,
      timeout: Duration.seconds(20),
      environment: sourcesEnv,
    });
    allSources(analysisFn);
    this.addRoutes(props, new HttpLambdaIntegration('AnalysisIntegration', analysisFn), [
      ['/analysis/series', apigw.HttpMethod.GET],
    ]);

    const adviceFn = new PythonFunction(this, 'Advice', {
      functionName: 'coach-advice',
      handlerModule: 'coach/advice/handler',
      description: 'Daily advice: facts computed in code, text written by the flow model',
      timeout: Duration.seconds(28),
      environment: {
        ...sourcesEnv,
        ADVICE_TABLE: props.adviceTable.tableName,
        ADVICE_MODEL_ID: props.adviceModelId,
        ...(props.guardrail ? { GUARDRAIL_ID: props.guardrail.id, GUARDRAIL_VERSION: props.guardrail.version } : {}),
      },
    });
    allSources(adviceFn);
    props.adviceTable.grantReadWriteData(adviceFn);
    // A global/us inference profile routes to the model in several regions, so the
    // caller needs the profile plus the underlying model in every region it may use.
    const modelName = props.adviceModelId.replace(/^(global|us|eu|apac)\./, '');
    adviceFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel'],
        resources: [
          `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/${props.adviceModelId}`,
          `arn:aws:bedrock:*::foundation-model/${modelName}*`,
          `arn:aws:bedrock:::foundation-model/${modelName}*`,
        ],
      }),
    );
    if (props.guardrail) {
      adviceFn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['bedrock:ApplyGuardrail'],
          resources: [`arn:aws:bedrock:${this.region}:${this.account}:guardrail/${props.guardrail.id}`],
        }),
      );
    }
    this.addRoutes(props, new HttpLambdaIntegration('AdviceIntegration', adviceFn), [
      ['/advice/latest', apigw.HttpMethod.GET],
      ['/advice/refresh', apigw.HttpMethod.POST],
    ]);
    new scheduler.Schedule(this, 'AdviceSchedule', {
      scheduleName: 'coach-daily-advice',
      description: 'Daily advice after the morning syncs',
      schedule: scheduler.ScheduleExpression.cron({
        hour: '7',
        minute: '30',
        timeZone: TimeZone.EUROPE_LONDON,
      }),
      target: new schedulerTargets.LambdaInvoke(adviceFn, { retryAttempts: 1 }),
    });

    const { agentId, agentAliasId, agentRuntimeArn } = props.chatBackends;
    const chatFn = new PythonFunction(this, 'Chat', {
      functionName: 'coach-chat',
      handlerModule: 'coach/chat/handler',
      description: 'Coach chat: Bedrock Agent (Module C) or AgentCore Runtime (Module G)',
      timeout: Duration.seconds(29), // HTTP API gives up at 30 s
      environment: {
        ...baseEnv,
        CHAT_TABLE: props.chatTable.tableName,
        ...(agentId && agentAliasId ? { AGENT_ID: agentId, AGENT_ALIAS_ID: agentAliasId } : {}),
        ...(agentRuntimeArn ? { AGENT_RUNTIME_ARN: agentRuntimeArn } : {}),
      },
    });
    props.chatTable.grantReadWriteData(chatFn);
    if (agentId && agentAliasId) {
      chatFn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['bedrock:InvokeAgent'],
          resources: [`arn:aws:bedrock:${this.region}:${this.account}:agent-alias/${agentId}/${agentAliasId}`],
        }),
      );
    }
    if (agentRuntimeArn) {
      chatFn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['bedrock-agentcore:InvokeAgentRuntime'],
          resources: [agentRuntimeArn, `${agentRuntimeArn}/runtime-endpoint/*`],
        }),
      );
    }
    this.addRoutes(props, new HttpLambdaIntegration('ChatIntegration', chatFn), [
      ['/chat', apigw.HttpMethod.POST],
      ['/chat/{sessionId}', apigw.HttpMethod.GET],
    ]);

    new CfnOutput(this, 'GetDailyMetricsArn', { value: getDailyMetricsFn.functionArn });
    new CfnOutput(this, 'LogDqsEntryArn', { value: logDqsFn.functionArn });
    new CfnOutput(this, 'CalculateRampRateArn', { value: rampRateFn.functionArn });
  }

  private addRoutes(
    props: CoachApiStackProps,
    integration: apigw.HttpRouteIntegration,
    routes: [string, apigw.HttpMethod][],
  ): void {
    routes.forEach(([path, method]) => {
      new apigw.HttpRoute(this, `Route${method}${path.replace(/[^A-Za-z]/g, '')}`, {
        httpApi: props.httpApi,
        routeKey: apigw.HttpRouteKey.with(path, method),
        integration,
        authorizer: props.authorizer,
      });
    });
  }
}
