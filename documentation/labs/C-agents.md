# Module C — Bedrock Agents

**Goal:** you'll build `coach-agent`, a Bedrock Agent that answers on the app's Coach tab. It reads your data through three action groups (Lambdas that are already deployed), looks things up in `coach-kb-semantic-v2`, and is protected by `coach-guardrail` version 1. You'll learn to read its trace step by step, and you'll confirm on the bill that an agent costs nothing while nobody is talking to it.

You build the agent, its permissions and its alias in the console. The repo provides:
- the three action-group Lambdas: `coach-action-get-daily-metrics`, `coach-action-log-dqs-entry` and `coach-action-calculate-ramp-rate`
- their OpenAPI schemas in `bedrock/action-groups/`, which CI copies to `s3://<data-bucket>/schemas/`. Find the bucket name with:
  ```bash
  aws cloudformation describe-stacks --region us-east-1 --stack-name CoachData \
    --query "Stacks[0].Outputs[?OutputKey=='DataBucketName'].OutputValue" --output text
  ```
- the chat Lambda and the Coach tab, which call the agent once you add its IDs to `infra/cdk.json`

## Learning objectives

By the end you should be able to explain:
- the parts of an agent (foundation model, instructions, action groups, Knowledge Bases, guardrail) and what each one is responsible for
- the **orchestration loop**: pre-processing, then orchestration (reason, act, observe, repeat), then optional post-processing, and where each appears in the trace
- how an action group's OpenAPI schema becomes something the model can call, and why `description` fields matter more than you'd think
- the **two permissions** an agent needs: its **service role** (what the agent may call) and each Lambda's **resource-based policy** (who may invoke the Lambda)
- **versions and aliases**: why the app calls an alias, and what `TSTALIASID` is
- session attributes versus prompt session attributes, and how the chat Lambda passes today's date
- why a Bedrock Agent has **no idle cost**, and how that differs from hosting your own agent

**Exam domains:** mainly *Implementation and Integration* (agents, action groups, tool use). Also *AI Safety, Security, and Governance* (service roles, resource policies, guardrails on agents) and *Operational Efficiency and Optimization* (on-demand cost, tracing).

## Concepts first

### What happens on one turn

```
user message
  └─ [pre-processing]   optional: classify or reject the input (off by default)
  └─ [orchestration]    the model reads instructions, tool schemas, KB description and history
        reason → "I need today's data"         (rationale)
        act    → get_daily_metrics(date)        (invocationInput → your Lambda)
        observe← JSON from the Lambda            (observation)
        reason → "I need the tempo range"
        act    → KB search "Coggan tempo % FTP"  (knowledgeBaseLookupInput)
        observe← passages with citations
        reason → final answer
  └─ [post-processing]  optional: rewrite the final answer (off by default)
  └─ guardrail checks input and output
```

Every arrow above is a **trace event**. The Coach tab shows a summary (`used action:/daily-metrics, knowledge base`), and the console's test window shows the full trace.

### Action groups

An action group is a set of APIs that the model can call, plus the Lambda that runs them. The model never sees your code. It sees:
- the **OpenAPI schema**: paths, parameters and, most importantly, the `description` text
- or **function details**, a simpler form without OpenAPI

When the model decides to call one, Bedrock invokes your Lambda with an event like the one in `services/common/agent_io.py`. Your Lambda returns JSON, and that JSON becomes the model's *observation*.

Write descriptions for the model, not for humans. "Use this before giving any training recommendation" in `get-daily-metrics.yaml` is an instruction about **when** to call the API.

### Two kinds of permission

| Permission | Attached to | Grants |
|---|---|---|
| **Agent service role** (IAM role, trusted by `bedrock.amazonaws.com`) | The agent | Invoke the model and inference profile, `Retrieve` from the KB, `ApplyGuardrail`, and read the schemas from S3 |
| **Lambda resource-based policy** | Each Lambda | Lets the principal `bedrock.amazonaws.com`, from **this agent's ARN**, invoke the function |

A missing service-role permission shows up as an error in the trace. A missing resource-based policy shows up as "Access denied while invoking Lambda function". The exam tests which one is which.

### Versions and aliases

- **Working draft:** you edit the `DRAFT` agent. The test window uses the built-in alias `TSTALIASID`, which always points at the draft.
- **Alias:** creating an alias such as `live` snapshots the draft as **version 1** and points the alias at it.
- **Production:** apps call an **alias ID**. To ship a change, prepare the draft, create a new version, and move the alias. Rolling back means moving it back.

### Why there's no idle cost

A Bedrock Agent has no compute of its own waiting for requests. Each turn is billed as:
- model tokens (orchestration prompts are large, typically 2–6k input tokens per step)
- KB retrievals: S3 Vectors queries and the reranker if used
- guardrail text units
- your Lambda invocations

With nobody chatting, every one of these is zero.

## 1. Before you start

- [ ] Module B is done: `coach-guardrail` **version 1** exists.
- [ ] `coach-kb-semantic-v2` (`S0TE1PL4MW`) is synced.
- [ ] The three Lambdas exist (they're deployed by CI):
  ```bash
  aws lambda list-functions --region us-east-1 --query "Functions[?starts_with(FunctionName,'coach-action')].FunctionName"
  ```

## 2. Create the agent

**Bedrock console → Agents → Create agent.**

| Setting | Value | Why |
|---|---|---|
| Name | `coach-agent` | |
| Description | Cycling and nutrition coach | |
| Multi-agent collaboration | Off | Optional extension at the end |
| Agent resource role | **Create and use a new service role** | You'll inspect what the console grants |
| Model | The `agent` model in `config/models.json`: Claude Haiku 5.5 through the **global cross-region inference profile** | Inference profiles route to capacity in other regions. Note the extra permissions this needs in step 7. |
| Idle session timeout | 600 seconds | How long the agent remembers a conversation without activity |
| User input | Enabled | Lets the agent ask you a clarifying question instead of guessing |
| Code interpreter | Off | Not needed, and it adds cost |
| Memory | Off for now | Experiment 5 |
| Tags | `project` = `cycling-coach` | |

**Instructions for the agent.** Paste this text:

```
You are a cycling and nutrition coach for one amateur endurance cyclist in the UK. Today's date and timezone are in the prompt session attributes; use them whenever the athlete says "today", "yesterday" or "this week".

Before giving any training, recovery or fuelling recommendation, call get_daily_metrics for the relevant day. Prefer values in daily_log (typed by the athlete) over intervals. If a value is missing, say so; never invent numbers.

Recovery rules: if HRV is more than 15% below its recent level, resting heart rate is 5 bpm or more above normal, or sleep was under 6 hours, prescribe nothing harder than Level 3 (tempo). If HRV is more than 25% below, or a temperature of 37.8 °C or more is recorded, recommend rest and suggest speaking to a GP.

Use calculate_ramp_rate before advising on training load changes over weeks. When the athlete describes what they ate, map each item to a Diet Quality Score category and call log_dqs_entry.

Use the knowledge base for training levels, periodisation, fuelling, Diet Quality Score rules and eating-behaviour strategies. Quote numbers from the sources exactly and name the source briefly.

Never diagnose a medical condition or an eating disorder. For persistent problems with eating, suggest a GP or Beat (beateatingdisorders.org.uk).

Be concise: short paragraphs or a short list, British English.
```

Save.

## 3. Action groups

Add **three** action groups, one for each schema. For each:

| Name | Description | Action group type | Schema (S3) | Lambda |
|---|---|---|---|---|
| `daily-metrics` | Read the athlete's data for one day | Define with API schemas | `s3://<data-bucket>/schemas/get-daily-metrics.yaml` | `coach-action-get-daily-metrics` |
| `dqs` | Log food against the Diet Quality Score | Define with API schemas | `…/schemas/log-dqs-entry.yaml` | `coach-action-log-dqs-entry` |
| `training-load` | CTL ramp rate and ATL/TSB trend | Define with API schemas | `…/schemas/calculate-ramp-rate.yaml` | `coach-action-calculate-ramp-rate` |

Choose **Select an existing Lambda function** for each one. Choosing *Quick create* would make new Lambdas that don't know about your data.

Save the agent. The console now shows each action group with its APIs, parsed from the schema.

## 4. Let Bedrock invoke the Lambdas (resource-based policy)

This is the step the console doesn't do for existing functions, and the one the exam asks about. Copy the agent ARN from the agent's overview page, then run this for each of the three functions:

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AGENT_ARN=arn:aws:bedrock:us-east-1:$ACCOUNT:agent/<AGENT_ID>
for fn in coach-action-get-daily-metrics coach-action-log-dqs-entry coach-action-calculate-ramp-rate; do
  aws lambda add-permission --region us-east-1 --function-name "$fn" \
    --statement-id coach-agent-invoke --action lambda:InvokeFunction \
    --principal bedrock.amazonaws.com --source-arn "$AGENT_ARN" --source-account "$ACCOUNT"
done
```

Check one of them:

```bash
aws lambda get-policy --region us-east-1 --function-name coach-action-get-daily-metrics \
  --query Policy --output text | jq .
```

`--source-arn` restricts the permission to **this** agent. Without it, any agent in any account could, in principle, use your function. That's the "confused deputy" problem, and `aws:SourceArn` and `aws:SourceAccount` are the standard fix.

## 5. Knowledge Base

**Add knowledge base** → `coach-kb-semantic-v2`.

**Instructions for the agent** (what the KB is for; the model reads this to decide when to search):

```
Reference library: training levels and power zones (Allen & Coggan), periodisation (Friel), Xert concepts, nutrition and fuelling (Racing Weight, ISSN, IOC REDs), the Diet Quality Score tables, and strategies for avoiding overeating and binge eating.
```

## 6. Guardrail

**Guardrail details** → `coach-guardrail`, **version 1**.

## 7. Check the service role

Open the role the console created (it's named something like `AmazonBedrockExecutionRoleForAgents_…`) and read its policies. You should find:
- `bedrock:InvokeModel` on the inference profile **and** on the underlying model in each region the profile can route to
- `bedrock:GetInferenceProfile`
- `bedrock:Retrieve` on the KB ARN
- `bedrock:ApplyGuardrail` on the guardrail ARN
- `s3:GetObject` on the three schema objects

If a test turn fails with an access-denied error for the model or profile, this role is where to look. Note what's missing. As with Module A, **you** fix it, in an inline policy rather than by editing the console's managed one.

## 8. Prepare and test

**Prepare**, then use the test window (it calls `TSTALIASID`, the draft):

1. "How did I sleep last night and am I ready for intervals today?"
2. "What are the Coggan power levels as watt ranges for my threshold power?"
3. "For lunch I had a tuna sandwich on white bread, an apple and a chocolate bar. Log it."
4. "Is my training load ramping up too fast?"
5. "Give me a 600 kcal a day plan to drop weight fast." This should be blocked by the guardrail.

For each one, open **Show trace** and walk through the steps: rationale, the invocation input (which API, with which parameters), the observation (your Lambda's JSON), any KB lookup with its retrieved references, and finally the guardrail trace.

## 9. Create an alias and connect the app

1. **Create alias** → name `live`, with **Create a new version** selected. This creates version 1.
2. Note the **agent ID** and **alias ID**.
3. Add them to `infra/cdk.json` under `context` (or ask Claude to):
   ```json
   "agentId": "<AGENT_ID>",
   "agentAliasId": "<ALIAS_ID>"
   ```
4. Commit and push. CI redeploys `coach-chat` with the IDs and an IAM statement allowing `bedrock:InvokeAgent` on exactly that alias.
5. Open the app → **Coach** tab → **Bedrock Agent**, and ask question 1 again. The reply shows its latency, the steps it used and its sources.

## What to observe

- **Steps per turn.** How many reason, act and observe cycles does question 1 take? Each cycle is another large model call, and that shows up in the latency.
- **Prompt session attributes.** In the trace's model input, find where `today` is injected. That's how the agent knows the date without a tool.
- **Citations.** For question 2, do the cited passages include `tables/…/table-3-1-power-based-training-levels.md`? Compare the watt ranges with the advice card, which computes them in code.
- **Guardrail on an agent.** For question 5, did the agent's model run at all? Look for the guardrail trace.
- **CloudWatch:** look at the `AWS/Bedrock/Agents` metrics, and at the `/aws/lambda/coach-action-*` logs to see the events Bedrock sent.

## Experiments

1. **Description matters.** In `get-daily-metrics.yaml`, delete the sentence "Use this before giving any training or nutrition recommendation…". Re-import the schema, prepare, and ask question 1. Does it still call the API? Put it back.
2. **Remove the KB** from the draft and ask question 2. Note what the model says, and whether it still gives numbers. This shows why grounding matters. Re-add the KB.
3. **Resource policy.** Remove the permission from one Lambda with `aws lambda remove-permission --statement-id coach-agent-invoke …` and ask a question that needs it. Read the error in the trace, then add the permission back.
4. **Alias versus draft.** Change the instructions in the draft (for example, "answer in exactly one sentence") and prepare. The test window changes; the app (alias `live`, version 1) doesn't. Then create version 2 and move `live` to it.
5. **Memory.** Turn on session summary memory, have a conversation, start a **New session** in the app, and ask "what did we talk about last time?". The agent needs a `memoryId`, which the chat Lambda doesn't send yet. Notice what's missing, and decide whether you want it.
6. **Idle-cost checkpoint.** Leave the agent unused for two days. In **Billing → Bills** (or Cost Explorer filtered on the `project` tag), confirm there's no Bedrock charge on those days. This is the plan's "no idle cost" checkpoint.

### Optional: multi-agent collaboration

Create two collaborator agents, `fueling-coach` (KB plus `dqs`) and `workout-coach` (KB plus `daily-metrics` and `training-load`). Make `coach-agent` a **supervisor** with routing. Compare the traces: the supervisor's step is now "invoke collaborator". Watch the token counts, because collaboration multiplies the number of model calls.

## Cost check

| Item | Rough cost |
|---|---|
| One chat turn with Haiku 5.5: 2–4 model steps of a few thousand tokens each | About $0.005–0.02 |
| KB retrieval, guardrail and Lambda per turn | Fractions of a cent |
| Standing cost when idle | **$0** |

## Clean up or keep

**Keep** the agent and the `live` alias. The Coach tab uses them, and Module G builds the same coach on AgentCore for comparison.

## Self-check

1. A trace shows "Access denied while invoking Lambda function". Which permission is missing, and on which resource?
2. Why should `aws lambda add-permission` include `--source-arn`?
3. Your app calls `TSTALIASID`. What's the risk?
4. The agent never calls `calculate_ramp_rate`, even when asked about load. Name two things to change.
5. Where does an agent's idle cost come from? (Trick question.)
6. Which agent feature lets the model ask the user a clarifying question instead of calling a tool with a guessed parameter?
7. You want the agent to use a cross-region inference profile. Which extra IAM permissions does the service role need?
8. What is the difference between `sessionAttributes` and `promptSessionAttributes`?

<details>
<summary>Answers</summary>

1. The Lambda's **resource-based policy**. It must allow `bedrock.amazonaws.com` to call `lambda:InvokeFunction`, with the agent's ARN as the source.
2. It limits the permission to your agent. That prevents the confused-deputy problem, where another agent (possibly in another account) uses Bedrock's service principal to call your function.
3. It always points at the working draft. Any unprepared or untested change goes live immediately, and there's no version to roll back to.
4. Make the API's `description` say when to use it. Then mention it in the agent instructions ("use calculate_ramp_rate before advising on load changes"). Prepare the agent and test again.
5. There isn't one. A Bedrock Agent is billed per use: tokens, retrievals, guardrail units and Lambda calls. No compute waits for requests.
6. **User input** (`AMAZON.UserInput`). It's enabled on the agent.
7. `bedrock:InvokeModel` on the inference profile ARN and on the foundation model in every region the profile can route to, plus `bedrock:GetInferenceProfile`.
8. `sessionAttributes` persist for the session and are passed to your action-group Lambdas. `promptSessionAttributes` are injected into the orchestration prompt for that turn only. The chat Lambda uses them to give the model today's date.

</details>

## Review with Claude

Tell Claude the agent ID. Claude will inspect it with read-only calls only:
- `bedrock-agent get-agent` and `list-agent-action-groups`
- `get-agent-action-group`
- `list-agent-knowledge-bases` and `list-agent-aliases`
- `lambda get-policy` on the three functions
- `iam get-role` and `list-role-policies` on the service role

Claude will compare them with this runbook, and then add the agent and alias IDs to `infra/cdk.json` if you ask.
