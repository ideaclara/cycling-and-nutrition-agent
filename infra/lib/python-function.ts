import * as path from 'path';
import { Duration, RemovalPolicy } from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';

const SERVICES_DIR = path.join(__dirname, '..', '..', 'services');

export interface PythonFunctionProps {
  /** Module path relative to services/, e.g. "strava/list_activities/handler". */
  readonly handlerModule: string;
  readonly functionName: string;
  readonly description?: string;
  readonly memorySize?: number;
  readonly timeout?: Duration;
  readonly environment?: Record<string, string>;
  readonly reservedConcurrentExecutions?: number;
}

/**
 * A Python Lambda packaged from the whole services/ directory so every function
 * can import the shared `common` package. Only the standard library and boto3
 * (bundled with the runtime) are used, so no Docker bundling step is needed.
 */
export class PythonFunction extends lambda.Function {
  constructor(scope: Construct, id: string, props: PythonFunctionProps) {
    const logGroup = new logs.LogGroup(scope, `${id}Logs`, {
      logGroupName: `/aws/lambda/${props.functionName}`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    super(scope, id, {
      functionName: props.functionName,
      description: props.description,
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: `${props.handlerModule.replace(/\//g, '.')}.handler`,
      code: lambda.Code.fromAsset(SERVICES_DIR, {
        exclude: ['.venv', 'uv.lock', 'tests', '**/__pycache__', '**/*.pyc', '.pytest_cache', '.ruff_cache', 'pyproject.toml'],
      }),
      memorySize: props.memorySize ?? 256,
      timeout: props.timeout ?? Duration.seconds(10),
      environment: props.environment,
      reservedConcurrentExecutions: props.reservedConcurrentExecutions,
      logGroup,
    });
  }
}
