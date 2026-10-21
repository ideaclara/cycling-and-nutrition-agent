#!/usr/bin/env node
import * as fs from 'fs';
import * as path from 'path';
import { App, Tags } from 'aws-cdk-lib';
import { ApiStack } from '../lib/api-stack';
import { CicdStack } from '../lib/cicd-stack';
import { CoachApiStack } from '../lib/coach-api-stack';
import { DataStack } from '../lib/data-stack';
import { FrontendStack } from '../lib/frontend-stack';
import { IntervalsStack } from '../lib/intervals-stack';
import { StravaStack } from '../lib/strava-stack';
import { WithingsStack } from '../lib/withings-stack';

const models = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'config', 'models.json'), 'utf8'));

const app = new App();
const ctx = (key: string): string => {
  const value = app.node.tryGetContext(key);
  if (typeof value !== 'string' || value.length === 0 || value.startsWith('REPLACE_ME')) {
    throw new Error(`Set CDK context value '${key}' in infra/cdk.json (or pass -c ${key}=...)`);
  }
  return value;
};

function optionalContext(key: string): string | undefined {
  const value = app.node.tryGetContext(key);
  return typeof value === 'string' && value ? value : undefined;
}

// Set after Module B: -c guardrailId=<id> -c guardrailVersion=1 (or in cdk.json).
function optionalGuardrail(): { id: string; version: string } | undefined {
  const id = optionalContext('guardrailId');
  return id ? { id, version: optionalContext('guardrailVersion') ?? '1' } : undefined;
}

// Everything lives in the region named in config/models.json (us-east-1).
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: models.region as string };
const projectTag = { key: 'project', value: 'cycling-coach' };
Tags.of(app).add(projectTag.key, projectTag.value);

const data = new DataStack(app, 'CoachData', {
  env,
  budgetEmail: ctx('budgetEmail'),
  monthlyBudgetUsd: 100,
  projectTag,
});

const api = new ApiStack(app, 'CoachApiGateway', { env });

new StravaStack(app, 'CoachStrava', {
  env,
  activitiesTable: data.stravaActivities,
  dataBucket: data.dataBucket,
  httpApi: api.httpApi,
  authorizer: api.authorizer,
  backfillStartEpoch: Date.UTC(2026, 0, 1) / 1000,
});

new WithingsStack(app, 'CoachWithings', {
  env,
  withingsTable: data.withingsTelemetry,
  secretName: 'prod/withings/credentials',
});

new IntervalsStack(app, 'CoachIntervals', {
  env,
  athleteId: ctx('athleteId'),
  intervalsTable: data.intervalsDaily,
  activitiesTable: data.intervalsActivities,
  httpApi: api.httpApi,
  authorizer: api.authorizer,
  backfillStartDate: '2026-01-01',
});

new CoachApiStack(app, 'CoachApi', {
  env,
  athleteId: ctx('athleteId'),
  withingsUserId: ctx('withingsUserId'),
  dailyLogTable: data.dailyFitnessLog,
  activitiesTable: data.stravaActivities,
  withingsTable: data.withingsTelemetry,
  readingsTable: data.manualReadings,
  intervalsTable: data.intervalsDaily,
  intervalsActivitiesTable: data.intervalsActivities,
  adviceTable: data.coachAdvice,
  chatTable: data.chatMessages,
  chatBackends: {
    agentId: optionalContext('agentId'),
    agentAliasId: optionalContext('agentAliasId'),
    agentRuntimeArn: optionalContext('agentRuntimeArn'),
  },
  adviceModelId: models.roles.flow.modelId as string,
  guardrail: optionalGuardrail(),
  httpApi: api.httpApi,
  authorizer: api.authorizer,
});

const frontend = new FrontendStack(app, 'CoachFrontend', {
  env,
  apiUrl: api.httpApi.apiEndpoint,
  userPoolId: api.userPool.userPoolId,
  userPoolClientId: api.userPoolClient.userPoolClientId,
});

new CicdStack(app, 'CoachCicd', {
  env,
  githubSubjectPrefix: ctx('githubSubjectPrefix'),
  amplifyAppId: frontend.appId,
  dataBucketArn: data.dataBucket.bucketArn,
  evalBucketArn: data.evalBucket.bucketArn,
});
