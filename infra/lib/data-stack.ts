import { CfnOutput, RemovalPolicy, Stack, StackProps } from 'aws-cdk-lib';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export interface DataStackProps extends StackProps {
  readonly budgetEmail: string;
  readonly monthlyBudgetUsd: number;
  /** Cost allocation tag (key=value) applied to every project resource. */
  readonly projectTag: { key: string; value: string };
}

/**
 * Stateful resources shared by every other stack. Everything here is RETAINed so
 * that tearing down a compute stack can never delete data.
 */
export class DataStack extends Stack {
  readonly stravaActivities: dynamodb.Table;
  readonly dailyFitnessLog: dynamodb.Table;
  readonly withingsTelemetry: dynamodb.Table;
  readonly manualReadings: dynamodb.Table;
  readonly intervalsDaily: dynamodb.Table;
  readonly dataBucket: s3.Bucket;
  readonly kbSourceBucket: s3.Bucket;
  readonly evalBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);

    const tableDefaults = {
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: RemovalPolicy.RETAIN,
    };

    // SK = "<start_date ISO>#<activityId>" so a descending Query with Limit 1
    // returns the newest activity (used as the `after` cursor for syncing).
    this.stravaActivities = new dynamodb.Table(this, 'StravaActivities', {
      ...tableDefaults,
      tableName: 'StravaActivities',
      partitionKey: { name: 'athleteId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'sk', type: dynamodb.AttributeType.STRING },
    });

    // One item per athlete per calendar day (SK = YYYY-MM-DD).
    this.dailyFitnessLog = new dynamodb.Table(this, 'DailyFitnessLog', {
      ...tableDefaults,
      tableName: 'DailyFitnessLog',
      partitionKey: { name: 'athleteId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'date', type: dynamodb.AttributeType.STRING },
    });

    // Same key schema as the eu-west-2 table so items copy across unchanged.
    this.withingsTelemetry = new dynamodb.Table(this, 'WithingsTelemetry', {
      ...tableDefaults,
      tableName: 'WithingsTelemetry',
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
    });

    // Blood pressure and temperature, several a day: SK = "<TYPE>#<ISO-8601 UTC>".
    this.manualReadings = new dynamodb.Table(this, 'ManualReadings', {
      ...tableDefaults,
      tableName: 'ManualReadings',
      partitionKey: { name: 'athleteId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'sk', type: dynamodb.AttributeType.STRING },
    });

    // Intervals.icu wellness + fitness/fatigue, one item per day (SK = YYYY-MM-DD).
    this.intervalsDaily = new dynamodb.Table(this, 'IntervalsDaily', {
      ...tableDefaults,
      tableName: 'IntervalsDaily',
      partitionKey: { name: 'athleteId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'date', type: dynamodb.AttributeType.STRING },
    });

    const bucketDefaults = {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.RETAIN,
    };

    // Overflow store for Strava activity payloads too large for a DynamoDB item,
    // plus the action-group OpenAPI schemas (schemas/) synced by CI.
    this.dataBucket = new s3.Bucket(this, 'DataBucket', bucketDefaults);

    // Reference documents for the Bedrock Knowledge Base (periodisation/,
    // nutrition/, power_models/). Versioned so re-uploads can be compared.
    // Nothing else goes in here: a Knowledge Base data source ingests every
    // supported file in the bucket.
    this.kbSourceBucket = new s3.Bucket(this, 'KbSourceBucket', { ...bucketDefaults, versioned: true });

    // eval_dataset.jsonl and Bedrock evaluation job output.
    this.evalBucket = new s3.Bucket(this, 'EvalBucket', { ...bucketDefaults, versioned: true });

    new CfnOutput(this, 'KbSourceBucketName', { value: this.kbSourceBucket.bucketName });
    new CfnOutput(this, 'EvalBucketName', { value: this.evalBucket.bucketName });
    new CfnOutput(this, 'DataBucketName', { value: this.dataBucket.bucketName });

    this.addProjectBudget(props.budgetEmail, props.monthlyBudgetUsd, props.projectTag);
  }

  /**
   * A budget scoped to this project's cost allocation tag. The account already has
   * an account-wide $100 budget and the default per-service anomaly monitor, so this
   * one answers "what is the lab itself costing?". The tag must be activated once in
   * Billing > Cost allocation tags before the budget sees any spend.
   */
  private addProjectBudget(email: string, limitUsd: number, tag: { key: string; value: string }): void {
    const subscribers = [{ subscriptionType: 'EMAIL', address: email }];
    const notification = (threshold: number, notificationType: 'ACTUAL' | 'FORECASTED') => ({
      notification: {
        comparisonOperator: 'GREATER_THAN',
        notificationType,
        threshold,
        thresholdType: 'PERCENTAGE',
      },
      subscribers,
    });

    new budgets.CfnBudget(this, 'ProjectBudget', {
      budget: {
        budgetName: 'cycling-coach-monthly',
        budgetType: 'COST',
        timeUnit: 'MONTHLY',
        budgetLimit: { amount: limitUsd, unit: 'USD' },
        costFilters: { TagKeyValue: [`user:${tag.key}$${tag.value}`] },
      },
      notificationsWithSubscribers: [
        notification(50, 'FORECASTED'),
        notification(80, 'FORECASTED'),
        notification(100, 'FORECASTED'),
        notification(100, 'ACTUAL'),
      ],
    });
  }
}
