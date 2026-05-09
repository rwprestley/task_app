import streamlit as st
import pandas as pd
import random
import math
import uuid
import requests
from datetime import date, datetime
import math

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
        response = requests.put(URL, json=tasks_list, headers=HEADERS)
        response.raise_for_status()
    except Exception as e:
        st.error(f"Failed to save tasks to the cloud! Error: {e}")
        if 'response' in locals():
            st.error(f'API Details: {response.text}')


# --- Core Math Logic ---
def roll_for_task(difficulty, urgency, battery_percent):
    """Calculates the roll and target based on task stats and battery."""
    target = round(difficulty * (1 - (urgency / 10)) * 2)
    base_roll = random.randint(1, 20)
    adjusted_roll = math.floor(base_roll * (battery_percent / 100))
    success = adjusted_roll >= target

    return success, base_roll, adjusted_roll, target

# --- Process recurring tasks ---
def process_recurring_tasks(tasks_list):
    """Calculates dynamic urgency and visibility for recurring tasks"""
    today = date.today()
    today_name = today.strftime('%A')
    today_str = today.strftime('%Y-%m-%d')
    modified = False

    for task in tasks_list:
        if task.get('Is_Recurring'):
            # Calculate days elapsed for interval math
            last_completed_str = task.get('Last_Completed_Date')
            if last_completed_str:
                last_completed = datetime.strptime(last_completed_str, '%Y-%m-%d').date()
                days_elapsed = (today - last_completed).days
            else:
                # If it's never been completed, force it to show up today
                days_elapsed = task['Interval_Max']

            # Check today's override settings
            override = task.get(f'{today_name}_Urgency', 'Auto')

            if override not in ['Auto', None]:
                # Hard-coded override logic
                new_urgency = int(override)
                new_status = 'Dormant' if new_urgency == 0 else 'Active'
            else:
                # Fallback interval logic
                least = task['Interval_Least']
                average = task['Interval_Average']
                maximum = task['Interval_Max']

                if days_elapsed < least:
                    # Task is dormant, hide it from active board
                    new_status = 'Dormant'
                    new_urgency = 0
                else:
                    # Task is active, calculate urgency
                    new_status = 'Active'
                    if days_elapsed >= maximum:
                        new_urgency = 10
                    elif days_elapsed < average: # Zone 1 - scale from 1 to 5
                        if average == least:
                            new_urgency = 5
                        else:
                            new_urgency = round(1 + 4 * ((days_elapsed - least) / (average - least)))
                    else: # Zone 2 - scale from 5 to 10
                        if maximum == average:
                            new_urgency = 10
                        else:
                            new_urgency = round(5 + 5 * ((days_elapsed - average) / (maximum - average)))

            # Apply calculated state to the task
            if task.get('Last_Completed_Date') == today_str:
                # If we already did it today, force it to stay completed
                if task['Status'] != 'Completed':
                    task['Status'] = 'Completed'
                    modified = True
            else:
                # Apply new urgency
                if task['Urgency'] != new_urgency:
                    task['Urgency'] = new_urgency
                    modified = True

                # Apply new status
                if new_status == 'Dormant':
                    if task['Status'] != 'Dormant':
                        task['Status'] = 'Dormant'
                        task['Done'] = False
                        modified = True
                elif new_status == 'Active':
                    # Only wake it up if it was dormant or completed
                    if task['Status'] in ['Dormant', 'Completed']:
                        task['Status'] = 'Active'
                        task['Done'] = False
                        modified = True

    return modified

# --- Define categories ---
CATEGORIES = ['Morning Routine', 'Work Tasks', 'Evening Tasks']

# --- App Layout & Configuration ---
st.set_page_config(page_title="RPG To-Do List", page_icon="🎲", layout='wide')
st.title("🎲 RPG To-Do List")

# --- Initialization & State Management ---
if 'tasks' not in st.session_state:
    st.session_state.tasks = load_tasks()
    if process_recurring_tasks(st.session_state.tasks):
        save_tasks(st.session_state.tasks)

# --- Celebration Logic ---
# This catches the flag AFTER the rerun so the animation actually plays when completing a task
if "celebration" in st.session_state:
    celeb = st.session_state.celebration
    st.toast(f"🎉 **{celeb['Task']}** completed! You beat a task with difficulty of {celeb['Difficulty']}.", icon="🎲")
    st.balloons()
    # Clear the flag so it doesn't loop infinitely
    del st.session_state["celebration"]

# 2. Daily Battery Input
battery = st.slider("Today's Battery (%)", 1, 100, 100)

# 3. Task Input Form
# Toggle for recurring logic
is_recurring = st.checkbox('Is this a recurring task?')

with st.form("new_task_form", clear_on_submit=True):
    st.write("### Add a New Task")
    task_name = st.text_input("Task")

    # Add category selection
    category = st.selectbox("Category", CATEGORIES)

    col1, col2 = st.columns(2)
    with col1:
        difficulty = st.slider("Difficulty", 1, 10, 5)
    with col2:
        urgency = st.slider('Urgency', 1, 10, 5)

    day_inputs = {}

    if is_recurring:
        col3, col4, col5 = st.columns(3)
        with col3:
            interval_least = st.number_input('Least Interval (Days)', min_value=1, value=1)
        with col4:
            interval_average = st.number_input('Average Interval (Days)', min_value=1, value=3)
        with col5:
            interval_max = st.number_input('Max Interval (Days)', min_value=2, value=7)


        st.write('**Day of the Week Overrides**')
        st.caption('Select an urgency (0-10) to override for each day (if necessary)')

        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        cols = st.columns(4)
        for i, day in enumerate(days):
            with cols[i % 4]:
                # Options are 'Auto', then 0 through 10
                day_inputs[f'{day}_Urgency'] = st.selectbox(day, options=['Auto'] + list(range(11)), index=0)
    else:
        interval_least, interval_average, interval_max = None, None, None
        # Provide default 'Auto' keys so NaNs are generated for one-off tasks
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
            day_inputs[f"{day}_Urgency"] = "Auto"


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
            st.warning(f'Failed. Rolled {adjusted_roll} (Base {base_roll}) vs Target {target}. Sent to backlog.')

        # Append the new task to master list
        new_task = {
            "ID": str(uuid.uuid4()), # Unique identifier
            "Done": False, # to become checkbox
            "Category": category,
            "Task": task_name,
            "Difficulty": difficulty,
            "Urgency": urgency,
            "Target": target,
            "Roll": adjusted_roll,
            "Status": status,
            "_Sort_Key": random.random(), # Generated ONCE per task
            "Is_Recurring": is_recurring,
            "Interval_Least": interval_least,
            "Interval_Average": interval_average,
            "Interval_Max": interval_max,
            "Last_Completed_Date": None
        }

        # Inject Monday-Sunday overrides into dictionary
        new_task.update(day_inputs)

        # SAVE TO CLOUD
        st.session_state.tasks.append(new_task)
        save_tasks(st.session_state.tasks)

# --- 🛠️ Master Quest Editor ---
with st.expander("🛠️ Master Quest Editor (Edit or Delete Tasks)"):
    st.write(
        "Edit any cell directly, or click the checkbox on the far left of a row and press your `Delete` key to remove a quest entirely.")

    if st.session_state.tasks:
        # Add a dropdown to select how you want to sort the data
        sort_by = st.selectbox(
            "Sort Admin Table By:",
            ["None (Default)", "Category", "Status", "Urgency", "Task Name"]
        )

        # Convert the master list to a DataFrame
        master_df = pd.DataFrame(st.session_state.tasks)

        # Apply Pandas sorting based on the dropdown selection
        if sort_by != "None (Default)":
            if sort_by == "Urgency":
                # Sort urgency Highest to Lowest
                master_df = master_df.sort_values(by="Urgency", ascending=False).reset_index(drop=True)
            elif sort_by == "Task Name":
                master_df = master_df.sort_values(by="Task", ascending=True).reset_index(drop=True)
            else:
                # Sort Category or Status Alphabetically
                master_df = master_df.sort_values(by=sort_by, ascending=True).reset_index(drop=True)

        # Define the exact order of columns left-to-right.
        # (Anything NOT in this list, like 'ID' or '_Sort_Key', will be automatically hidden!)
        admin_column_order = [
            "Task", "Category", "Status", "Done",
            "Difficulty", "Urgency", "Target", "Roll",
            "Is_Recurring", "Interval_Least", "Interval_Average", "Interval_Max", "Monday_Urgency", "Tuesday_Urgency", "Wednesday_Urgency",
            "Thursday_Urgency", "Friday_Urgency", "Saturday_Urgency", "Sunday_Urgency", "Last_Completed_Date"
        ]

        # 2. Display the data editor with 'dynamic' rows enabled
        edited_master_df = st.data_editor(
            master_df,
            num_rows="dynamic",  # This enables row deletions and additions!
            column_order=admin_column_order,
            column_config={
                'Task': st.column_config.TextColumn('Task Name', pinned=True),
                "Category": st.column_config.SelectboxColumn("Category", options=CATEGORIES),
                "Status": st.column_config.SelectboxColumn("Status", options=["Active", "Skipped", "Completed"])
            },
            key="master_quest_editor"
        )

        # Check if the dataframe actually changed to avoid spamming the API
        if st.button('💾 Save Admin Changes', type="primary"):
            # Bulletproof NaN scrubber: loop through every single cell
            # and forcefully convert Pandas 'NaN' or 'NaT' into standard Python 'None'
            raw_records = edited_master_df.to_dict('records')
            clean_tasks = []
            for record in raw_records:
                clean_record = {}
                for key, value in record.items():
                    if pd.isna(value):  # This catches NaN, NaT, and None reliably
                        clean_record[key] = None
                    else:
                        clean_record[key] = value
                clean_tasks.append(clean_record)

            # Save thoroughly sanitized data
            st.session_state.tasks = clean_tasks
            save_tasks(st.session_state.tasks)  # SAVE TO CLOUD
            st.success("Master list updated successfully!")
            st.rerun()
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

            # Use columns to put the header and reroll button on the same line
            col_head, col_btn = st.columns([3, 1])
            with col_head:
                st.write(f'### {current_category}')
            with col_btn:
                # Category-specific reroll button
                if st.button('🔄 Reroll Quests', key=f'reroll_{current_category}'):
                    # Update dynamic urgencies BEFORE rerolling
                    process_recurring_tasks(st.session_state.tasks)

                    for task in st.session_state.tasks:
                        if task['Category'] == current_category and task['Status'] != 'Dormant':
                            # Reset the checkmark and give a fresh sort key
                            task['Done'] = False
                            task['_Sort_Key'] = random.random()

                            # Reroll the task against the current battery slider
                            success, base_roll, adjusted_roll, target = roll_for_task(
                                task['Difficulty'], task['Urgency'], battery
                            )

                            # Update the task stats
                            task['Roll'] = adjusted_roll
                            task['Target'] = target
                            task['Status'] = 'Active' if success else 'Skipped'

                    save_tasks(st.session_state.tasks) # Save the reroll to the cloud
                    st.rerun() # Refresh the UI

            # Filter first by category
            cat_df = df[df['Category'] == current_category]

            if cat_df.empty:
                st.info(f"No quests in {current_category} yet.")
                continue # Skip the rest of the loop and move to the next tab

            # --- ACTIVE TASKS --- #
            st.write("### ⚔️ Today's Quest Board")
            active_df = cat_df[cat_df['Status'] == 'Active'].copy().reset_index(drop=True)

            if not active_df.empty:
                # Sort morning routine tasks randomly
                # if current_category == 'Morning Routine':
                active_df = active_df.sort_values(by=['_Sort_Key'], ascending=[True])
                # else:
                #     # Sort by urgency (highest first), then by the random number (generated on creation)
                #     active_df = active_df.sort_values(by=['Urgency', '_Sort_Key'], ascending=[False, True])

                # Capture the output of the data editor
                edited_active = st.data_editor(
                    active_df,
                    column_config={
                        "Done": st.column_config.CheckboxColumn("Done?", default=False, width='small')
                    },
                    column_order=['Done', 'Task', 'Difficulty'], #only show these columns
                    # Disable editing for everything except the "Done" checkbox
                    disabled=['Task', 'Difficulty'],
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
                            if is_done:
                                task['Status'] = 'Completed'
                                # Set the flag for toast / balloons
                                st.session_state.celebration = {'Task': task['Task'], 'Target': task['Target'], 'Difficulty': task['Difficulty']}
                                if task.get('Is_Recurring'):
                                    task['Last_Completed_Date'] = date.today().strftime('%Y-%m-%d')
                            needs_rerun = True

                # Force a quick rerun to immediately reflect the completed status
                if needs_rerun:
                    save_tasks(st.session_state.tasks)  # SAVE TO CLOUD
                    st.rerun()

            else:
                st.info("No active quests. You either rolled poorly or haven't added any!")

            # --- COMPLETED TASKS ---
            completed_df = cat_df[cat_df['Status'] == 'Completed'].copy().reset_index(drop=True)
            if not completed_df.empty:
                st.write('### 🏆 Vanquished To-Dos')
                edited_completed = st.data_editor(
                    completed_df,
                    column_order=['Task', 'Difficulty'],
                    disabled=['Task', 'Difficulty'],
                    hide_index=True,
                    key=f'completed_{current_category}'
                )

            # --- SKIPPED TASKS --- #
            st.write("### ⛺ The Backlog (Skipped)")
            skipped_df = cat_df[cat_df['Status'] == 'Skipped']
            skipped_df = skipped_df.sort_values(by=['Urgency', 'Difficulty'], ascending=[False, True])

            if not skipped_df.empty:
                st.data_editor(
                    skipped_df,
                    column_config={
                        'Done': st.column_config.CheckboxColumn("Done?", default=False, width='small')
                    },
                    column_order=['Done', 'Task', 'Difficulty'],
                    disabled=['Task', 'Difficulty'],
                    hide_index=True,
                    key=f'skipped_{current_category}'
                )
            else:
                st.info("Your backlog is clear.")
else:
    st.write("---")
    st.info("Fill out the form above to start building your Quest Board!")