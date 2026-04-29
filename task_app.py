import streamlit as st
import pandas as pd
import random
import math
import uuid
import requests

# --- Cloud Database Setup ---
BIN_ID = st.secrets["JSONBIN_ID"]
API_KEY = st.secrets["JSONBIN_KEY"]
URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
HEADERS = {
    "X-Master-Key": API_KEY,
    "Content-Type": "application/json"
}

def load_tasks():
    """Fetches your task list from the cloud."""
    try:
        response = requests.get(URL, headers=HEADERS)
        # JSONBin nests your data inside a 'record' key
        return response.json().get("record", [])
    except Exception as e:
        st.error("Failed to load cloud tasks. Starting fresh.")
        return []

def save_tasks(tasks_list):
    """Pushes your updated task list back to the cloud."""
    try:
        requests.put(URL, json=tasks_list, headers=HEADERS)
    except Exception as e:
        st.error("Failed to save tasks to the cloud!")


# --- Core Math Logic ---
def roll_for_task(difficulty, urgency, battery_percent):
    """Calculates the roll and target based on task stats and battery."""
    target = round(difficulty * (1 - (urgency / 10)) * 2)
    base_roll = random.randint(1, 20)
    adjusted_roll = math.floor(base_roll * (battery_percent / 100))
    success = adjusted_roll >= target

    return success, base_roll, adjusted_roll, target

# --- Define categories ---
CATEGORIES = ['Morning Routine', 'Work Tasks', 'Evening Tasks']

# --- App Layout & Configuration ---
st.set_page_config(page_title="RPG To-Do List", page_icon="🎲")
st.title("🎲 RPG To-Do List")

# 1. Initialize session state for your master task list
if 'tasks' not in st.session_state:
    st.session_state.tasks = load_tasks()

# 2. Daily Battery Input
battery = st.slider("Today's Battery (%)", 1, 100, 100)

# 3. Task Input Form
with st.form("new_task_form", clear_on_submit=True):
    st.write("### Add a New Task")
    task_name = st.text_input("Task")

    # Add category selection
    category = st.selectbox("Category", CATEGORIES)

    col1, col2 = st.columns(2)
    with col1:
        difficulty = st.slider("Difficulty", 1, 10, 5)
    with col2:
        urgency = st.slider("Urgency", 1, 10, 5)

    submitted = st.form_submit_button("Roll for Task!")

    if submitted and task_name:
        # Trigger the math logic
        success, base_roll, adjusted_roll, target = roll_for_task(difficulty, urgency, battery)

        # Determine status
        status = 'Active' if success else 'Skipped'

        # Show outcome to the user
        if success:
            st.success(f'Success! Rolled {adjusted_roll} (Base {base_roll}) vs Target {target}. Added to to-do list.')
            st.balloons()
        else:
            st.warning(f'Failed. Rolled {adjusted_roll} (Base {base_roll} vs Target {target}. Sent to backlog.')

        # Append the new task to master list
        st.session_state.tasks.append({
            "ID": str(uuid.uuid4()), # Unique identifier
            "Done": False, # to become checkbox
            "Category": category,
            "Task": task_name,
            "Difficulty": difficulty,
            "Urgency": urgency,
            "Target": target,
            "Roll": adjusted_roll,
            "Status": status,
            "_Sort_Key": random.random() # Generated ONCE per task
        })

        # SAVE TO CLOUD
        save_tasks(st.session_state.tasks)

# --- 🛠️ Master Quest Editor ---
with st.expander("🛠️ Master Quest Editor (Edit or Delete Tasks)"):
    st.write(
        "Edit any cell directly, or click the checkbox on the far left of a row and press your `Delete` key to remove a quest entirely.")

    if st.session_state.tasks:
        # 1. Convert the master list to a DataFrame
        master_df = pd.DataFrame(st.session_state.tasks)

        # 2. Display the data editor with 'dynamic' rows enabled
        edited_master_df = st.data_editor(
            master_df,
            num_rows="dynamic",  # This enables row deletions and additions!
            column_config={
                "Category": st.column_config.SelectboxColumn("Category", options=CATEGORIES),
                "Status": st.column_config.SelectboxColumn("Status", options=["Active", "Skipped", "Completed"])
            },
            key="master_quest_editor",
            use_container_width=True
        )

        # Check if the dataframe actually changed to avoid spamming the API
        if not edited_master_df.equals(master_df):
            st.session_state.tasks = edited_master_df.to_dict('records')
            save_tasks(st.session_state.tasks)  # SAVE TO CLOUD
    else:
        st.info("No quests available to edit.")

# 4. Display and Filter the Tables
# Only attempt to display tables if there are tasks in the list
if st.session_state.tasks:
    # Convert master list to a Pandas DataFrame for easy filtering
    df = pd.DataFrame(st.session_state.tasks)

    st.write("---")

    # Generate category tabs dynamically based on CATEGORIES list
    tabs = st.tabs(CATEGORIES)

    # Loop through each tab and populate it with filtered data
    for i, tab in enumerate(tabs):
        with tab:
            current_category = CATEGORIES[i]

            # Filter first by category
            cat_df = df[df['Category'] == current_category]

            if cat_df.empty:
                st.info(f"No quests in {current_category} yet.")
                continue # Skip the rest of the loop and move to the next tab

            # --- ACTIVE TASKS --- #
            st.write("### ⚔️ Today's Quest Board")
            active_df = cat_df[cat_df['Status'] == 'Active'].copy().reset_index(drop=True)

            if not active_df.empty:
                # Sort by urgency (highest first), then by the random number (generated on creation)
                active_df = active_df.sort_values(by=['Urgency', '_Sort_Key'], ascending=[False, True])

                # Capture the output of the data editor
                edited_active = st.data_editor(
                    active_df,
                    column_config={
                        "Done": st.column_config.CheckboxColumn("Done?", default=False)
                    },
                    # Disable editing for everything except the "Done" checkbox
                    disabled=['ID', 'Category', 'Task', 'Difficulty', 'Urgency', 'Target', 'Roll', 'Status'],
                    hide_index=True,
                    key=f'active_{current_category}' # Keys must be unique!
                )

                # Check for differences in the "Done" column
                needs_rerun = False

                for _, row in edited_active.iterrows():
                    task_id = row['ID']
                    is_done = row['Done']

                    # Find the specific task in session state and update it
                    for task in st.session_state.tasks:
                        if task['ID'] == task_id and task['Done'] != is_done:
                            task['Done'] = is_done
                            needs_rerun = True

                # Force a quick rerun to immediately reflect the completed status
                if needs_rerun:
                    save_tasks(st.session_state.tasks)  # SAVE TO CLOUD
                    st.rerun()

                # Drop the temporary column and ID column so it doesn't render in the UI
                active_df = active_df.drop(columns=['_Sort_Key', 'ID'])

            else:
                st.info("No active quests. You either rolled poorly or haven't added any!")

            # --- SKIPPED TASKS --- #
            st.write("### ⛺ The Backlog (Skipped)")
            skipped_df = cat_df[cat_df['Status'] == 'Skipped']
            skipped_df = skipped_df.sort_values(by=['Urgency', 'Difficulty'], ascending=[False, True])

            if not skipped_df.empty:
                st.data_editor(
                    skipped_df,
                    column_config={
                        'Done': st.column_config.CheckboxColumn("Done?", default=False)
                    },
                    disabled=['Category', 'Task', 'Difficulty', 'Urgency', 'Target', 'Roll', 'Status'],
                    hide_index=True,
                    key=f'skipped_{current_category}'
                )
            else:
                st.info("Your backlog is clear.")
else:
    st.write("---")
    st.info("Fill out the form above to start building your Quest Board!")