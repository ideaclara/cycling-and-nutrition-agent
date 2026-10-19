#!/usr/bin/env node
import * as fs from 'fs';
import * as path from 'path';
import { App, Tags } from 'aws-cdk-lib';
import { ApiStack } from '../lib/api-stack';
import { CicdStack } from '../lib/cicd-stack';
import { CoachApiStack } from '../lib/coach-api-stack';
import { DataStack } from '../lib/data-stack';
import { FrontendStack } from '../lib/frontend-stack';
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

new CoachApiStack(app, 'CoachApi', {
  env,
  athleteId: ctx('athleteId'),
  withingsUserId: ctx('withingsUserId'),
  dailyLogTable: data.dailyFitnessLog,
  activitiesTable: data.stravaActivities,
  withingsTable: data.withingsTelemetry,
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
  githubRepo: ctx('githubRepo'),
  amplifyAppId: frontend.appId,
  kbSourceBucketArn: data.kbSourceBucket.bucketArn,
  evalBucketArn: data.evalBucket.bucketArn,
});
