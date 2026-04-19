import anthropic
import os
import json

client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY")
)

# --- Tools the agent can use ---
# In a real agent these would call APIs, read files, query databases
# For now they are simple functions so you can see the pattern clearly

def get_metric_summary(metric_name):
    """Simulates fetching a metric from a database"""
    fake_data = {
        "creators_active": {"value": 1250, "wow_change": -8.3, "vs_forecast": -12.1},
        "post_per_creator": {"value": 2.8, "wow_change": -15.2, "vs_forecast": -19.8},
        "click_per_post": {"value": 39, "wow_change": -15.2, "vs_forecast": -18.3},
        "order_per_click": {"value": 0.028, "wow_change": -15.2, "vs_forecast": -19.8},
    }
    if metric_name in fake_data:
        return json.dumps(fake_data[metric_name])
    return json.dumps({"error": f"Metric {metric_name} not found"})

def check_seasonality(date, metric):
    """Simulates checking seasonality assumptions"""
    return json.dumps({
        "date": date,
        "metric": metric,
        "expected_uplift_pct": 6.0,
        "driver": "Festival week",
        "actual_uplift_pct": -15.2,
        "verdict": "Seasonality assumption did NOT hold"
    })

def send_alert(message):
    """Simulates sending a WhatsApp/Slack alert"""
    print(f"\n[ALERT SENT]: {message}\n")
    return json.dumps({"status": "sent", "message": message})

# --- Tool definitions for Claude ---
# This is how you tell Claude what tools exist and what they do
tools = [
    {
        "name": "get_metric_summary",
        "description": "Fetches current value, WoW change, and forecast variance for a metric",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": "Name of the metric: creators_active, post_per_creator, click_per_post, order_per_click"
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
        "description": "Sends an alert message when a critical issue is found",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The alert message to send"}
            },
            "required": ["message"]
        }
    }
]

# --- Tool executor ---
# Maps tool names to actual functions
def execute_tool(tool_name, tool_input):
    if tool_name == "get_metric_summary":
        return get_metric_summary(tool_input["metric_name"])
    elif tool_name == "check_seasonality":
        return check_seasonality(tool_input["date"], tool_input["metric"])
    elif tool_name == "send_alert":
        return send_alert(tool_input["message"])
    return json.dumps({"error": "Unknown tool"})

# --- The agent loop ---
def run_agent(goal):
    print(f"\n AGENT STARTING")
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

        # If Claude is done reasoning and has a final answer
        if response.stop_reason == "end_turn":
            final = next(
                (b.text for b in response.content if hasattr(b, "text")), 
                "Done"
            )
            print(f"\n AGENT FINISHED")
            print(f"Final output: {final}")
            return final

        # If Claude wants to use a tool
        if response.stop_reason == "tool_use":
            # Add Claude's response to message history
            messages.append({"role": "assistant", "content": response.content})

            # Execute each tool Claude requested
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

            # Add tool results back to message history
            messages.append({"role": "user", "content": tool_results})

        # Safety: stop after 10 steps to prevent infinite loops
        if step >= 10:
            print("Max steps reached")
            break

# --- Run it ---
run_agent("""
You are a growth analytics agent for an Indian e-commerce company.
Today is 2025-04-20.

Your job:
1. Check all 4 key metrics: creators_active, post_per_creator, click_per_post, order_per_click
2. For any metric more than 10% below forecast, check if seasonality held
3. If seasonality failed on any metric, send an alert with a clear summary
4. Give me a final 3-line summary of what you found
""")