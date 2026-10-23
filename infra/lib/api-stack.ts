import { CfnOutput, Duration, RemovalPolicy, Stack, StackProps } from 'aws-cdk-lib';
import * as apigw from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpJwtAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ses from 'aws-cdk-lib/aws-ses';
import { Construct } from 'constructs';
import { PythonFunction } from './python-function';

/** Patterns of email addresses allowed to sign up (documentation/labs/05-sign-in.md). */
export const SIGNUP_ALLOWLIST_PARAMETER = '/cycling-coach/signup-allowlist';

export interface ApiStackProps extends StackProps {
  /**
   * Domain that sends sign-up and MFA emails (from no-reply@<domain>). Creates the
   * SES domain identity; its DKIM records are stack outputs to add to DNS.
   */
  readonly authEmailDomain?: string;
  /**
   * Phase 2, once SES shows the domain as verified: Essentials plan, email through
   * SES, and a password plus an emailed six-digit code at every sign-in.
   */
  readonly emailMfa?: boolean;
}

/**
 * The shared HTTP API and the Cognito pool that protects it.
 *
 * Sign-up is open only to email addresses that match the allowlist in SSM,
 * checked by a pre-sign-up trigger. The email address is the username.
 */
export class ApiStack extends Stack {
  readonly httpApi: apigw.HttpApi;
  readonly authorizer: HttpJwtAuthorizer;
  readonly userPool: cognito.UserPool;
  readonly userPoolClient: cognito.UserPoolClient;

  constructor(scope: Construct, id: string, props: ApiStackProps = {}) {
    super(scope, id, props);

    const domain = props.authEmailDomain;
    if (domain) {
      const identity = new ses.EmailIdentity(this, 'AuthEmailDomain', { identity: ses.Identity.domain(domain) });
      identity.dkimRecords.forEach(
        (record, i) => new CfnOutput(this, `AuthEmailDkim${i + 1}`, { value: `${record.name} CNAME ${record.value}` }),
      );
    }
    if (props.emailMfa && !domain) {
      throw new Error('emailMfa needs authEmailDomain: MFA codes are sent through SES');
    }

    // Email MFA settings. Cognito won't let email be both the MFA channel and the only
    // recovery channel, so a forgotten password is reset by an administrator instead.
    const emailMfa: Partial<cognito.UserPoolProps> =
      props.emailMfa && domain
        ? {
            featurePlan: cognito.FeaturePlan.ESSENTIALS,
            mfa: cognito.Mfa.REQUIRED,
            mfaSecondFactor: { sms: false, otp: false, email: true },
            email: cognito.UserPoolEmail.withSES({
              fromEmail: `no-reply@${domain}`,
              fromName: 'Cycling Coach',
              sesRegion: this.region,
              sesVerifiedDomain: domain,
            }),
            accountRecovery: cognito.AccountRecovery.NONE,
          }
        : {};

    // The email address is the username (signInAliases email only).
    this.userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: 'cycling-coach-users',
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      passwordPolicy: { minLength: 12, requireSymbols: false },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: RemovalPolicy.RETAIN,
      ...emailMfa,
    });

    const preSignUp = new PythonFunction(this, 'PreSignUp', {
      functionName: 'coach-pre-signup',
      handlerModule: 'coach/auth/pre_signup/handler',
      description: 'Rejects sign-ups whose email does not match the allowlist in SSM',
      environment: { ALLOWLIST_PARAMETER: SIGNUP_ALLOWLIST_PARAMETER },
    });
    preSignUp.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['ssm:GetParameter'],
        resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter${SIGNUP_ALLOWLIST_PARAMETER}`],
      }),
    );
    this.userPool.addTrigger(cognito.UserPoolOperation.PRE_SIGN_UP, preSignUp);

    // Public SPA client: no secret; Amplify Auth signs in with SRP.
    this.userPoolClient = this.userPool.addClient('WebClient', {
      userPoolClientName: 'cycling-coach-web',
      generateSecret: false,
      authFlows: { userSrp: true },
      accessTokenValidity: Duration.hours(1),
      idTokenValidity: Duration.hours(1),
      refreshTokenValidity: Duration.days(30),
    });

    this.httpApi = new apigw.HttpApi(this, 'HttpApi', {
      apiName: 'cycling-coach-api',
      description: 'Daily log, Strava sync/OAuth and Withings read endpoints',
      // Bearer tokens (not cookies) are used, so any origin is safe here and the
      // Amplify domain doesn't need to be known before the frontend stack exists.
      corsPreflight: {
        allowOrigins: ['*'],
        allowMethods: [
          apigw.CorsHttpMethod.GET,
          apigw.CorsHttpMethod.PUT,
          apigw.CorsHttpMethod.POST,
          apigw.CorsHttpMethod.DELETE,
        ],
        allowHeaders: ['Authorization', 'Content-Type'],
        maxAge: Duration.hours(1),
      },
    });

    this.authorizer = new HttpJwtAuthorizer(
      'CognitoAuthorizer',
      `https://cognito-idp.${this.region}.amazonaws.com/${this.userPool.userPoolId}`,
      { jwtAudience: [this.userPoolClient.userPoolClientId] },
    );

    new CfnOutput(this, 'ApiUrl', { value: this.httpApi.apiEndpoint });
    new CfnOutput(this, 'UserPoolId', { value: this.userPool.userPoolId });
    new CfnOutput(this, 'UserPoolClientId', { value: this.userPoolClient.userPoolClientId });
  }
}
