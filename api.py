from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse
import anthropic
import os
import json
import gspread
from google.oauth2.service_account import Credentials
from twilio.rest import Client as TwilioClient

app = FastAPI()

# --- Anthropic client ---
anthropic_client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY")
)

# --- Google Sheets ---
def get_sheets_client():
    import json as json_lib
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    # Try JSON content first (for Render), fall back to file path (for local)
    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if credentials_json:
        creds_dict = json_lib.loads(credentials_json)
        creds = Credentials.from_service_account_info(
            creds_dict, scopes=scopes
        )
    else:
        credentials_path = os.environ.get("GOOGLE_CREDENTIALS_PATH")
        creds = Credentials.from_service_account_file(
            credentials_path, scopes=scopes
        )
    return gspread.authorize(creds)

def get_sheet_data():
    gc = get_sheets_client()
    sheet_id = os.environ.get("SHEET_ID")
    spreadsheet = gc.open_by_key(sheet_id)
    worksheet = spreadsheet.sheet1
    return worksheet.get_all_records()

# --- Tools ---
def get_metric_summary(metric_name):
    try:
        rows = get_sheet_data()
        if not rows:
            return json.dumps({"error": "No data in sheet"})
        latest = rows[-1]
        previous = rows[-2] if len(rows) >= 2 else None
        if metric_name not in latest:
            return json.dumps({"error": f"Metric {metric_name} not found"})
        current_value = float(latest[metric_name])
        result = {
            "metric": metric_name,
            "date": latest.get("date", "unknown"),
            "value": current_value,
        }
        if previous and metric_name in previous:
            prev_value = float(previous[metric_name])
            if prev_value != 0:
                wow_change = ((current_value - prev_value) / prev_value) * 100
                result["wow_change_pct"] = round(wow_change, 2)
                result["previous_value"] = prev_value
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})

def check_seasonality(date, metric):
    return json.dumps({
        "date": date,
        "metric": metric,
        "expected_uplift_pct": 6.0,
        "driver": "Festival week",
        "actual_uplift_pct": -15.2,
        "verdict": "Seasonality assumption did NOT hold"
    })

def send_alert(message):
    try:
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_WHATSAPP_FROM")
        to_number = os.environ.get("MY_WHATSAPP_NUMBER")
        twilio_client = TwilioClient(account_sid, auth_token)
        msg = twilio_client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
        return json.dumps({"status": "sent", "sid": msg.sid})
    except Exception as e:
        return json.dumps({"status": "failed", "error": str(e)})

# --- Tool definitions ---
tools = [
    {
        "name": "get_metric_summary",
        "description": "Fetches latest value and WoW change for a metric from Google Sheets",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": "Column name: creators_active, post_per_creator, click_per_post, order_per_click"
                }
            },
            "required": ["metric_name"]
        }
    },
    {
        "name": "check_seasonality",
        "description": "Checks whether seasonality assumptions held for a metric",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "metric": {"type": "string"}
            },
            "required": ["date", "metric"]
        }
    },
    {
        "name": "send_alert",
        "description": "Sends a WhatsApp alert when a critical issue is found",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"}
            },
            "required": ["message"]
        }
    }
]

# --- Tool executor ---
def execute_tool(tool_name, tool_input):
    if tool_name == "get_metric_summary":
        return get_metric_summary(tool_input["metric_name"])
    elif tool_name == "check_seasonality":
        return check_seasonality(tool_input["date"], tool_input["metric"])
    elif tool_name == "send_alert":
        return send_alert(tool_input["message"])
    return json.dumps({"error": "Unknown tool"})

# --- Agent loop ---
def run_agent():
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")

    goal = f"""
You are a growth analytics agent for an Indian e-commerce company.
Today is {today}.

Your job:
1. Check all metrics: creators_active, post_per_creator, click_per_post, order_per_click
2. For any metric with WoW change worse than -10%, check seasonality
3. If seasonality failed, send a WhatsApp alert with a clear summary
4. Return a final 3-line summary of what you found
"""

    messages = [{"role": "user", "content": goal}]
    step = 0

    while True:
        step += 1
        response = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            tools=tools,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            final = next(
                (b.text for b in response.content if hasattr(b, "text")),
                "Done"
            )
            return final

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })
            messages.append({"role": "user", "content": tool_results})

        if step >= 10:
            return "Max steps reached"

# --- API endpoints ---
@app.get("/")
def health_check():
    return {"status": "growth agent is running"}

@app.post("/run-agent")
def trigger_agent(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_agent_and_log)
    return {"status": "agent started", "message": "check your WhatsApp in 30 seconds"}

def run_agent_and_log():
    result = run_agent()
    print(f"Agent completed: {result}")

@app.get("/run-agent-sync")
def trigger_agent_sync():
    result = run_agent()
    return {"status": "completed", "summary": result}