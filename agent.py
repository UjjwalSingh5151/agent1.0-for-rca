import anthropic
import os
import json
import gspread
from google.oauth2.service_account import Credentials

client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY")
)

# --- Google Sheets connection ---
def get_sheets_client():
    credentials_path = os.environ.get("GOOGLE_CREDENTIALS_PATH")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(
        credentials_path,
        scopes=scopes
    )
    return gspread.authorize(creds)

def get_sheet_data():
    gc = get_sheets_client()
    sheet_id = os.environ.get("SHEET_ID")
    spreadsheet = gc.open_by_key(sheet_id)
    worksheet = spreadsheet.sheet1
    return worksheet.get_all_records()

# --- Real tool: reads from Google Sheets ---
def get_metric_summary(metric_name):
    try:
        rows = get_sheet_data()
        if not rows:
            return json.dumps({"error": "No data in sheet"})

        # Get last two rows for WoW comparison
        latest = rows[-1]
        previous = rows[-2] if len(rows) >= 2 else None

        if metric_name not in latest:
            return json.dumps({"error": f"Metric {metric_name} not found in sheet"})

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

# --- Still simulated: seasonality check ---
def check_seasonality(date, metric):
    return json.dumps({
        "date": date,
        "metric": metric,
        "expected_uplift_pct": 6.0,
        "driver": "Festival week",
        "actual_uplift_pct": -15.2,
        "verdict": "Seasonality assumption did NOT hold"
    })

# --- Real alert: prints clearly, ready for WhatsApp next ---
def send_alert(message):
    try:
        from twilio.rest import Client
        
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_WHATSAPP_FROM")
        to_number = os.environ.get("MY_WHATSAPP_NUMBER")
        
        client_twilio = Client(account_sid, auth_token)
        
        msg = client_twilio.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
        
        print(f"\n{'='*60}")
        print(f"WHATSAPP ALERT SENT: {msg.sid}")
        print(f"{'='*60}\n")
        
        return json.dumps({"status": "sent", "sid": msg.sid})
        
    except Exception as e:
        print(f"Alert failed: {str(e)}")
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
                    "description": "Column name in the sheet: creators_active, post_per_creator, click_per_post, order_per_click"
                }
            },
            "required": ["metric_name"]
        }
    },
    {
        "name": "check_seasonality",
        "description": "Checks whether seasonality assumptions held for a metric on a given date",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                "metric": {"type": "string", "description": "Metric name to check"}
            },
            "required": ["date", "metric"]
        }
    },
    {
        "name": "send_alert",
        "description": "Sends an alert when a critical issue is found",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Alert message to send"}
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
def run_agent(goal):
    print(f"\nAGENT STARTING")
    print(f"Goal: {goal}")
    print("=" * 60)

    messages = [{"role": "user", "content": goal}]
    step = 0

    while True:
        step += 1
        print(f"\n--- Step {step} ---")

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            tools=tools,
            messages=messages
        )

        print(f"Claude decided: {response.stop_reason}")

        if response.stop_reason == "end_turn":
            final = next(
                (b.text for b in response.content if hasattr(b, "text")),
                "Done"
            )
            print(f"\nAGENT FINISHED")
            print(f"Final output:\n{final}")
            return final

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"Using tool: {block.name}({block.input})")
                    result = execute_tool(block.name, block.input)
                    print(f"Tool result: {result}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })

            messages.append({"role": "user", "content": tool_results})

        if step >= 10:
            print("Max steps reached")
            break

# --- Run ---
run_agent("""
You are a growth analytics agent for an Indian e-commerce company.
Today is 2025-04-21.

Your job:
1. Check all metrics in the sheet: creators_active, post_per_creator, 
   click_per_post, order_per_click
2. For any metric with WoW change worse than -10%, check seasonality
3. If seasonality failed, send an alert with a clear summary
4. Give me a final 3-line summary of what you found
""")