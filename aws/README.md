# AWS build: deploy, test, and clean up

This guide deploys the hotel booking assistant on AWS. The stack is an Amazon Bedrock Agent (Amazon Nova Pro) that calls an AWS Lambda action handler backed by two Amazon DynamoDB tables, plus a Bedrock Knowledge Base for general hotel questions. The Lambda, tables, and IAM permissions are deployed with AWS SAM. The agent, action group, and Knowledge Base are created in the AWS console.

For the project overview and the comparison with the local build, see the [root README](../README.md).

## Where commands run

- Every `sam` command runs from the `aws/` folder.
- Every other command states its working directory in its code fence: `cwd=root` means the repository root (the folder that contains `aws/`, `agent/`, `knowledge-base/`, and `local/`), and `cwd=aws` means the `aws/` folder.
- Placeholders in angle brackets, such as `<your-bucket>`, are values you choose or look up. Each one is explained where it first appears.

## Prerequisites

- An AWS account and permission to create DynamoDB tables, Lambda functions, IAM roles, S3 buckets, and Bedrock resources.
- Region `us-east-1` for everything.
- AWS SAM CLI, AWS CLI v2, and Python 3.12.
- AWS credentials configured locally (`aws configure`, or `aws configure --profile <profile>`). Confirm they work:

```bash cwd=root
aws sts get-caller-identity
```

- Bedrock model access for **Amazon Nova Pro** in `us-east-1`: open the Amazon Bedrock console, choose **Model access**, enable **Amazon Nova Pro**, and wait until its status shows access granted. The agent cannot run without this.

## No access keys? Use AWS CloudShell

If your IAM user cannot create access keys, deploy from AWS CloudShell. CloudShell supplies AWS CLI credentials for the signed-in user, so no access keys are needed.

1. In the AWS console, switch to `us-east-1` and open CloudShell.
2. Zip the `aws/` and `agent/` folders (and `knowledge-base/` if you want to upload the Knowledge Base files from CloudShell) on your machine.
3. In CloudShell choose **Actions**, then **Upload file**, and upload the zip.
4. Unzip it in the CloudShell home folder. Keep the folder names, so `aws/` stays next to `agent/`.
5. Install the SAM CLI in CloudShell if `sam --version` reports command not found, then continue with the steps below. In CloudShell, run the commands from the unzipped `aws/` folder.

## Deploy

1. Create an S3 bucket for the SAM deployment artifacts. Bucket names are global, so choose a unique name and use it as `<your-bucket>` everywhere below.

   ```bash cwd=root
   aws s3 mb s3://<your-bucket> --region us-east-1
   ```

2. Build the Lambda package.

   ```bash cwd=aws
   sam build
   ```

3. Deploy with the bucket from step 1.

   ```bash cwd=aws
   sam deploy --s3-bucket <your-bucket>
   ```

4. Review the changeset that SAM prints before you confirm. Cancel if it shows a **Delete** or **Modify** action on any resource that your own stack did not create. On a first deployment into an empty stack, every row should be an **Add**.

5. Record the stack Outputs. You need all four later:

   | Output | Used for |
   |---|---|
   | `InventoryTableName` | Seeding inventory, checking counts |
   | `BookingsTableName` | Checking booking records |
   | `BookingActionHandlerArn` | Reference for the action group |
   | `BookingActionHandlerName` | Selecting the Lambda in the action group, direct Lambda test |

   View them with the CLI, or open the CloudFormation console, select the stack, and open the **Outputs** tab:

   ```bash cwd=root
   aws cloudformation describe-stacks --stack-name <stack-name> --query "Stacks[0].Outputs" --region us-east-1
   ```

   `<stack-name>` is `hotel-booking-assistant` unless you override it.

**S3 bucket options.** `--resolve-s3` and `--s3-bucket` are mutually exclusive. The committed `aws/samconfig.toml` sets neither, so the documented deploy command supplies `--s3-bucket <your-bucket>`. Do not add `resolve_s3` to `aws/samconfig.toml` while you pass `--s3-bucket`.

**Shared AWS account.** If other people deploy this project in the same account, choose a unique `<suffix>` so resource names do not collide:

```bash cwd=aws
sam deploy --stack-name hotel-booking-<suffix> --s3-bucket <your-bucket> --parameter-overrides ProjectName=hotel-booking-<suffix>
```

With this override, the table names become `hotel-booking-<suffix>-inventory` and `hotel-booking-<suffix>-bookings`, the Lambda becomes `hotel-booking-<suffix>-action-handler`, and the stack is `hotel-booking-<suffix>`. Use those names in every later command. The `Outputs` always show the real names.

## Seed the inventory

The seed loads 12 dates (2026-12-20 to 2026-12-31), including the deliberate edge cases used by the test scenarios.

**Option A: script.** Use the `InventoryTableName` Output as the table argument. Add `--profile <profile>` if you use a named profile.

```bash cwd=root
python aws/scripts/seed_inventory.py --table <InventoryTableName> --region us-east-1
python aws/scripts/seed_inventory.py --table <InventoryTableName> --region us-east-1 --profile <profile>
```

The script needs `boto3`. Install it if Python reports `No module named boto3`:

```bash cwd=root
python -m pip install boto3
```

**Option B: PartiQL.** Open `aws/data/inventory_seed.partiql.sql`, and paste the statements one at a time into the DynamoDB console **PartiQL editor**. The table name in that file assumes the default `ProjectName`. Edit it if you overrode `ProjectName`.

**Verify.** A successful seed produces 12 items. In the DynamoDB console, open **Tables**, select the inventory table, choose **Explore table items**, and confirm that 12 rows are listed.

## Create the Knowledge Base

> **Cost warning.** The OpenSearch Serverless collection that backs the Knowledge Base incurs cost for as long as it exists, including when no queries run. Delete it as soon as you finish (see [Clean up](#clean-up)).

1. Create or pick an S3 bucket for the knowledge-base documents (`<kb-bucket>`). Upload the three files from the root `knowledge-base/` folder (`amenities-and-dining.md`, `faq.md`, `hotel-policies.md`) to the prefix `s3://<kb-bucket>/hotel-kb/`.

   ```bash cwd=root
   aws s3 cp knowledge-base/ s3://<kb-bucket>/hotel-kb/ --recursive --region us-east-1
   ```

2. In the Bedrock console, open **Knowledge bases** and choose **Create**.
   - Data source: the S3 prefix `s3://<kb-bucket>/hotel-kb/`.
   - Embeddings model: **Titan Text Embeddings V2**.
   - Vector store: let Bedrock create one (OpenSearch Serverless quick create).
3. After creation, open the data source and choose **Sync**. Wait until the sync completes.
4. Copy the Knowledge Base ID from the Knowledge Base details page. This guide calls it `<KB_ID>`.

## Create the Bedrock Agent

The agent, its action group, and the Knowledge Base are created in the console. They are outside the SAM template. The template does grant `bedrock.amazonaws.com` permission to invoke the Lambda (scoped to your account), so you add no extra Lambda permission.

1. Bedrock console, **Agents**, **Create agent**. Name it `hotel-booking-assistant`.
2. Foundation model: **Amazon Nova Pro**.
3. Instructions: paste the full contents of `agent/agent-instructions.txt`.
4. Enable **User input** so the agent can ask clarifying questions (scenario 5 needs it).
5. Add an **Action group**:
   - Name: `booking-actions`.
   - Action group type: **Define with API schemas**.
   - Lambda function: the function named by the `BookingActionHandlerName` Output.
   - API schema: **Define via in-line schema editor**, and paste the contents of `agent/action-group-schema.json`.
6. Add the Knowledge Base from the previous section. For its instruction, use: "Use this knowledge base to answer general questions about hotel policies, amenities, dining, parking, pets, Wi-Fi, check-in and check-out, and cancellations."
7. **Save**, then **Prepare** the agent.
8. Create an alias (for example `prod`) so that you test a stable version.
9. Copy the agent ID from the agent overview page (`<AGENT_ID>`) and the alias ID from the **Aliases** section (`<ALIAS_ID>`).

**Model note.** Amazon Nova Pro is the tested foundation model. Newer Claude models returned the error "data retention mode 'default' is not available for this model" when selected for the agent.

## Run the mocked logic tests

These tests run the Lambda code against an in-memory fake of DynamoDB. They need no AWS account and no network access. They cover booking an available room, refusing a sold-out room, booking the last room, a missing room type, and two racing bookings for the last room.

```bash cwd=root
python -m pip install boto3
python aws/scripts/local_test.py
```

The tests passed when every line starts with `PASS` and the last line is `All local logic tests passed.` Any line starting with `FAIL` means a check failed.

The Lambda itself needs no extra packages. `aws/src/booking_handler/requirements.txt` lists none, because `boto3` is part of the Python 3.12 Lambda runtime. The local test imports `boto3`, so install it on your machine as shown above.

## Direct Lambda test (no agent)

This calls `/checkAvailability` for 2026-12-22 straight on the Lambda. Replace `<BookingActionHandlerName>` with the Output value.

**bash or CloudShell:**

```bash cwd=root
aws lambda invoke --function-name <BookingActionHandlerName> --cli-binary-format raw-in-base64-out --payload '{"apiPath":"/checkAvailability","httpMethod":"GET","actionGroup":"booking-actions","parameters":[{"name":"date","value":"2026-12-22"}]}' out.json && cat out.json
```

**PowerShell** (AWS CLI v2 expects the payload base64-encoded by default):

```powershell cwd=root
$p = '{"apiPath":"/checkAvailability","httpMethod":"GET","actionGroup":"booking-actions","parameters":[{"name":"date","value":"2026-12-22"}]}'
$b = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($p))
aws lambda invoke --function-name <BookingActionHandlerName> --payload $b out.json
Get-Content out.json
```

**Expected result** on a freshly seeded table: `out.json` holds a response envelope with `"messageVersion": "1.0"` and `"httpStatusCode": 200`. The `body` string under `responseBody` / `application/json` contains `"status": "ok"`, `"seaView": 10`, and `"gardenView": 8` for `2026-12-22`.

## Test scenarios

Run these in the Bedrock console agent **Test** panel, using the alias you created. Counts are Sea View / Garden View on a freshly seeded inventory table.

**Re-seed before each full run.** Scenario 6 books the last Sea View room for 2026-12-29, and scenarios 3 and 6 reduce counts, so re-seed to restore all 12 rows:

```bash cwd=root
python aws/scripts/seed_inventory.py --table <InventoryTableName> --region us-east-1
```

Re-seeding overwrites the inventory rows. It does not delete booking records from earlier runs, so those stay in the bookings table until you delete them.

| # | Prompt | Tool operation called | Booking ID / booking record | Counts before to after |
|---|---|---|---|---|
| 1 | "What time is check-out?" | No booking tool. The answer comes from the knowledge base: 11:00 AM. | No ID, no record | No inventory change |
| 2 | "How many rooms are available on 2026-12-22?" | `checkAvailability` | No ID, no record | 2026-12-22: 10 / 8 to 10 / 8 |
| 3 | "Book a Sea View room for 2026-12-22 for Jane Doe, jane@example.com" | `bookRoom` | ID returned, one new record | 2026-12-22: Sea View 10 to 9, Garden View 8 to 8 |
| 4 | "Book a Sea View room for 2026-12-25 for John Smith" | `bookRoom` (refused) | No ID, no record | 2026-12-25: Sea View 0 to 0, Garden View 2 to 2 |
| 5 | "I'd like to book a room for 2026-12-27" | None before the assistant asks for a missing detail | No ID, no record | 2026-12-27: 10 / 4 to 10 / 4 |
| 6 | "Book a Sea View room for 2026-12-29 for Priya Patel" | `bookRoom` | First request: ID returned, exactly one record. Second identical request: refused, no ID, no second record | 2026-12-29: Sea View 1 to 0 after the first request and 0 after the second. Garden View 0 to 0 |
| 7 | "Book a Sea View room for 2026-12-31 for Sam Lee", then "Book a Garden View room for 2026-12-31 for Sam Lee" | `bookRoom` (both refused) | No ID, no record | 2026-12-31: 0 / 0 to 0 / 0 |

What to check for each scenario:

1. The agent answers 11:00 AM from the knowledge base. No action group call appears in the trace, and no count changes.
2. The agent reports 10 Sea View and 8 Garden View rooms.
3. The agent returns a booking ID. The bookings table gains one record, and the 2026-12-22 Sea View count drops from 10 to 9.
4. The agent refuses and says no Sea View rooms are available. The bookings table gains no record. The Sea View count stays 0 and the Garden View count stays 2.
5. The agent asks for at least one missing detail, such as the room type or the guest name, before booking. Nothing is booked, and the 2026-12-27 counts stay 10 Sea View and 4 Garden View.
6. The first request returns a booking ID and creates exactly one record, and the Sea View count goes from 1 to 0 (Garden View stays 0). **This scenario books the last Sea View room for 2026-12-29.** A second identical request is refused, returns no booking ID, creates no second record, and leaves the Sea View count at 0. Re-seed before you repeat it.
7. Both requests are refused. No booking record is created, and both counts stay 0.

To verify counts and records, open the inventory table in the DynamoDB console before and after each booking, refresh the item, and check the bookings table for a new record (scenarios 3 and 6) or for none (scenarios 4 and 7).

**Optional overbooking check.** To exercise the atomic guarantee directly on the Lambda, set the 2026-12-29 Sea View count to 1 and invoke `bookRoom` twice at nearly the same time from two terminals with `aws lambda invoke`. Exactly one response has status `confirmed`, and the other has status `unavailable`.

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| `S3 Bucket does not exist` | The `--s3-bucket` value is misspelled, or the bucket is in another region. | Create the bucket in `us-east-1` with `aws s3 mb`, or correct the name. |
| Error that `--resolve-s3` and `--s3-bucket` conflict | Both options are set, for example `resolve_s3` was added to `aws/samconfig.toml` and `--s3-bucket` is also on the command line. | Use only one. The committed `aws/samconfig.toml` sets neither. |
| "data retention mode 'default' is not available for this model" | A newer Claude model is selected as the agent's foundation model. | Select Amazon Nova Pro, then save and prepare the agent again. |
| Timeout or model error in the Test panel that disappears on a second try | Transient model latency. | Send the same message again. |
| `AccessDeniedException`, or a message about model access | Amazon Nova Pro is not enabled for the account. | Bedrock console, **Model access**, enable Amazon Nova Pro in `us-east-1`. |
| The agent says it cannot invoke the function | The Lambda has no resource permission for `bedrock.amazonaws.com`. | Redeploy the stack, which creates the permission. Or add it with `aws lambda add-permission` for the Bedrock service principal and your account. |

## Clean up

Delete in this order. Most of these resources were created in the console and are not part of the SAM stack.

1. The Bedrock Agent, including its alias.
2. The Knowledge Base.
3. The OpenSearch Serverless collection that backs the Knowledge Base. It incurs cost while it exists, including when no queries run, so do not skip this step.
4. The knowledge-base S3 bucket `<kb-bucket>`. Empty it first, then delete it.
5. The SAM stack, with your own stack name:

   ```bash cwd=aws
   sam delete --stack-name <stack-name> --region us-east-1
   ```

6. The SAM deployment bucket `<your-bucket>`. Empty it first, then delete it.
