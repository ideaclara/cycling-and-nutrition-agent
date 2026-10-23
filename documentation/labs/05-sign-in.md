# 05 — Sign-in: allowlisted sign-up and email MFA

**Goal:** anyone on your allowlist can create an account, with their email address as
the username. Every sign-in then needs the password **and** a six-digit code that
Cognito emails from `no-reply@<your domain>`.

## How it works

```
Sign up ──> Cognito ──> pre-sign-up trigger (coach-pre-signup) ──> SSM /cycling-coach/signup-allowlist
                                                                    (reject unless the email matches)
Sign in ──> password ──> Cognito emails a 6-digit code through SES ──> code ──> tokens for the API
```

- **Username:** the email address (`UsernameAttributes: email`). There's no separate username.
- **Allowlist:** an SSM parameter, so your addresses stay out of the public repo and you
  can change the list without a deploy. Patterns are separated by commas or new lines,
  matched without regard to case, and `*` matches anything:
  - `matt@example.com`: one address
  - `dave*@*.*`: any address starting "dave", at any domain with a dot
  - `*@gmail.com`: anyone with a Gmail address
  - `*@*`: **anyone at all**. Every account can read all of your training, health and
    food data, because the API serves one athlete. Use it only for a short demo.
- **Fails closed:** if the parameter is missing or empty, nobody can sign up. Users you
  create with `admin-create-user` aren't checked.
- **MFA codes need SES:** Cognito's built-in email can't send MFA codes, and email MFA
  needs the **Essentials** feature plan. That plan includes 10,000 monthly active users
  free; SES costs $0.10 per 1,000 emails.
- **No self-service password reset:** Cognito won't let email be both the MFA channel and
  the only recovery channel, so "Forgot password" is switched off. Reset a password with
  the admin command in step 6.

The change is deployed in two phases, because Cognito can't use SES until the domain is
verified:

| Phase | `infra/cdk.json` | What's live |
|---|---|---|
| 1 | `authEmailDomain` set, `emailMfa: "false"` | Allowlisted sign-up, SES domain identity waiting for DNS |
| 2 | `emailMfa: "true"` | Essentials plan, email through SES, password + code at every sign-in |

## 1. Create the allowlist

```bash
aws ssm put-parameter --region us-east-1 --name /cycling-coach/signup-allowlist \
  --type String --value 'you@yourdomain.com' --tags Key=project,Value=cycling-coach
```

To change it later, run the same command with `--overwrite` instead of `--tags`. To see it:

```bash
aws ssm get-parameter --region us-east-1 --name /cycling-coach/signup-allowlist --query Parameter.Value --output text
```

## 2. Verify the domain in SES (after the phase 1 deploy)

The deploy creates the SES identity for the domain and prints three DKIM records as
outputs of the `CoachApiGateway` stack:

```bash
aws cloudformation describe-stacks --region us-east-1 --stack-name CoachApiGateway \
  --query "Stacks[0].Outputs[?starts_with(OutputKey, 'AuthEmailDkim')].OutputValue" --output text
```

Each line is `<name> CNAME <value>`. Add the three CNAME records at your DNS provider,
then wait until SES says the domain is verified (usually minutes, up to 72 hours):

```bash
aws sesv2 get-email-identity --region us-east-1 --email-identity yourdomain.com \
  --query '{verified: VerifiedForSendingStatus, dkim: DkimAttributes.Status}'
```

You want `verified: true` and `dkim: "SUCCESS"`.

**SES sandbox:** a new SES account can only send to verified addresses. With the domain
verified, that's any address at your domain. To send codes to anyone else on the
allowlist (a Gmail address, say), request **production access** in the SES console
(Account dashboard → Request production access). That's an account-level request, so
you make it yourself.

## 3. Switch on email MFA (phase 2)

Set `"emailMfa": "true"` in `infra/cdk.json`, commit and push. CI deploys it.

## 4. Test

1. Open the app and sign in with your password. Cognito emails a six-digit code from
   `no-reply@yourdomain.com`. Enter it.
2. In a private window, choose **Create Account** with an address that isn't on the
   allowlist. You should see "PreSignUp failed with error This email address isn't
   allowed to sign up."
3. Add a test address to the allowlist and sign up with it. Cognito emails a
   verification code. After that, sign-in asks for the password and an emailed code.

## 5. Manage accounts

```bash
# list users
aws cognito-idp list-users --region us-east-1 --user-pool-id <pool-id> \
  --query 'Users[].{email: Attributes[?Name==`email`]|[0].Value, status: UserStatus, enabled: Enabled}'

# remove someone
aws cognito-idp admin-delete-user --region us-east-1 --user-pool-id <pool-id> --username <email>
```

The pool ID is the `UserPoolId` output of `CoachApiGateway`. Removing a pattern from the
allowlist stops new sign-ups only; it doesn't delete existing accounts.

## 6. Reset a forgotten password

```bash
read -rsp "New password: " PW; echo
aws cognito-idp admin-set-user-password --region us-east-1 --user-pool-id <pool-id> \
  --username <email> --password "$PW" --permanent
unset PW
```

## Cost

| Item | Cost |
|---|---|
| Cognito Essentials | Free up to 10,000 monthly active users |
| SES | $0.10 per 1,000 emails (one per sign-in or sign-up) |
| SSM parameter (standard) | Free |
| Pre-sign-up Lambda | Free at this volume |
