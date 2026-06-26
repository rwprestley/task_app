import streamlit as st
import pandas as pd
import random
import uuid
import requests
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import math
import json

# --- Cloud Database Setup ---
GIST_ID = st.secrets["GIST_ID"]
GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
GIST_URL = f"https://api.github.com/gists/{GIST_ID}"
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}
FILENAME = "quests.json"
timezone = ZoneInfo('US/Mountain')

def load_tasks():
    """Fetches your task list from private Github Gist."""
    try:
        response = requests.get(GIST_URL, headers=HEADERS)
        response.raise_for_status()
        gist_data = response.json()
        content = gist_data['files'][FILENAME]['content'] # parse back into Python list
        return json.loads(content)
    except Exception as e:
        st.error("Failed to load cloud tasks. Error: {e}")
        if 'response' in locals():
            st.error(f"API details: {response.text}")
        return []

def save_tasks(tasks_list):
    """Pushes your updated task list back to Github Gist."""
    try:
        # Github's API requries a specific nested JSON payload to update a file
        payload = {
            "files": {
                FILENAME: {
                    "content": json.dumps(tasks_list, indent=2)
                }
            }
        }
        # Note: use PATCH to update a Gist
        response = requests.patch(GIST_URL, headers=HEADERS, json=payload)
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

def calculate_hit_chance(target, current_battery):
    """Simulates all 20 sides of the die to find exact success probability."""
    successes = 0
    for base_roll in range(1, 21):
        adjusted_roll = math.floor(base_roll * (current_battery / 100))
        if adjusted_roll >= target:
            successes += 1
    return (successes / 20) * 100

# --- Process recurring tasks ---
def process_recurring_tasks(tasks_list):
    """Calculates dynamic urgency and visibility for recurring tasks"""
    now = datetime.now(timezone)
    today = now.date()
    today_name = now.strftime('%A')
    today_str = now.strftime('%Y-%m-%d')
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
                new_urgency = int(float(override))
                new_status = 'Dormant' if new_urgency == 0 else 'Active'
            else:
                # Fallback interval logic
                least = task.get('Interval_Least')
                least = int(least) if least is not None else 0
                average = task.get('Interval_Average')
                average = int(average) if average is not None else 1
                maximum = task.get('Interval_Max')
                maximum = int(maximum) if maximum is not None else 1

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

            # Automatic category sorting
            if task.get('Category') != 'Morning Routine': # Exclude morning routine tasks
                # Grab importance flag and current urgency
                is_important = task.get('Is_Important', False)
                current_urgency = task.get('Urgency', 5)

                # Check: is task highly urgent AND important?
                if current_urgency > 7 and is_important:
                    target_category = 'High Priority'
                else:
                    target_category = 'Medium Priority'

                # Promote or demote the task if it's in the wrong bin
                if task.get('Category') != target_category:
                    task['Category'] = target_category
                    modified = True

    return modified

# --- Process one-off tasks ---
def process_deadline_tasks(tasks_list):
    """Calculated dynamic urgency for one-off tasks approaching their due date"""
    today = datetime.now(timezone).date()
    modified = False

    for task in tasks_list:
        # Skip recurring tasks or tasks without due dates
        if task.get('Is_Recurring'):
            continue

        # Check for start date - transition to dormant state
        if task.get('Start_Date'):
            start_date = date.fromisoformat(task['Start_Date'])
            if today < start_date:
                if task.get('Status') != 'Dormant':
                    task['Status'] = 'Dormant'
                    task['Urgency'] = 0
                    modified = True
                continue

        # Wake the task up if its start date has arrived
        if task.get('Status') == 'Dormant':
            task['Status'] = 'Active'
            modified = True

        if task.get('Due_Date'): # Ratchet urgency (if task has a due date)
            due_date = date.fromisoformat(task['Due_Date'])
            base_urgency = task.get('Base_Urgency', 5)

            # Grab creation date
            creation_str = task.get('Creation_Date')
            creation_date = date.fromisoformat(creation_str) if creation_str else today

            # Determine if we should use the Ideal Date logic
            use_ideal = False
            if task.get('Ideal_Due_Date'):
                ideal_date = date.fromisoformat(task['Ideal_Due_Date'])
                if today <= ideal_date:
                    use_ideal = True

            # Calculate proportional linear urgency
            if use_ideal: # Creation to ideal date (target urgency: 7)
                total_days = (ideal_date - creation_date).days
                days_elapsed = (today - creation_date).days

                if total_days <= 0:
                    new_urgency = 7
                elif days_elapsed <= 0:
                    new_urgency = base_urgency
                else:
                    progress = days_elapsed / total_days
                    new_urgency = base_urgency + ((7 - base_urgency) * progress)

            else: # Creation to hard deadline (target urgency: 10)
                total_days = (due_date - creation_date).days
                days_elapsed = (today - creation_date).days

                if today >= due_date or total_days <= 0:
                    new_urgency = 10
                elif days_elapsed <= 0:
                    new_urgency = base_urgency
                else:
                    progress = days_elapsed / total_days
                    new_urgency = base_urgency + ((10 - base_urgency) * progress)

            # Round safely between 1 and 10
            new_urgency = max(1, min(10, int(round(new_urgency))))

            if task.get('Urgency') != new_urgency:
                task['Urgency'] = new_urgency
                modified = True

        # Automatic category sorting
        if task.get('Category') != 'Morning Routine': # Don't auto-sort morning routine one-off tasks
            current_urgency = task.get('Urgency', 5)
            is_important = task.get('Is_Important', False)

            # Check: both highly urgent AND important?
            if current_urgency > 7 and is_important:
                target_category = 'High Priority'
            else:
                target_category = 'Medium Priority'

            # Promote or demote the task if it's in the wrong bin
            if task.get('Category') != target_category:
                task['Category'] = target_category
                modified = True

    return modified

# --- Define categories ---
CATEGORIES = ['Morning Routine', 'High Priority', 'Medium Priority']

# --- App Layout & Configuration ---
st.set_page_config(page_title="RPG To-Do List", page_icon="🎲", layout='wide')
st.title("🎲 RPG To-Do List")

# --- Initialization & State Management ---
if 'tasks' not in st.session_state:
    st.session_state.tasks = load_tasks()
    needs_save_recurring = process_recurring_tasks(st.session_state.tasks)
    needs_save_deadlines = process_deadline_tasks(st.session_state.tasks)

    if needs_save_recurring or needs_save_deadlines:
        save_tasks(st.session_state.tasks)

if 'active_tab_memory' not in st.session_state:
    st.session_state.active_tab_memory = CATEGORIES[0]

# --- Celebration Logic ---
# This catches the flag AFTER the rerun so the animation actually plays when completing a task
if "celebration" in st.session_state:
    celeb = st.session_state.celebration
    st.toast(f"🎉 **{celeb['Task']}** completed! You beat a task with difficulty of {celeb['Difficulty']}.", icon="🎲")
    st.balloons()
    # Clear the flag so it doesn't loop infinitely
    del st.session_state["celebration"]

# 2. Daily Battery Input and Weekend Mode Toggle
weekend_mode = st.toggle("🌴 Weekend Mode")
battery = st.slider("Today's Battery (%)", 1, 100, 100)

# 3. Task Input Form
col_flags1, col_flags2, col_flags3 = st.columns(3)
with col_flags1:
    # Toggle for recurring logic
    is_recurring = st.checkbox('Is this a recurring task?')

with col_flags2:
    # Deadline UI
    has_deadline = st.checkbox("📅 Set a Deadline?")
    due_date_str = None
    ideal_date_str = None
    start_date_str = None

    if has_deadline:
        has_ideal = st.checkbox("Set an 'Ideal' early deadline?")
        has_start = st.checkbox("Set a start date?", help='Task will stay hidden until start date.')

with col_flags3:
    # Importance flag
    is_important = st.checkbox("Is this task important?",
                               help='Important tasks automatically move to High Priority when Urgency > 7. ')

with st.form("new_task_form", clear_on_submit=True):
    st.write("### Add a New Task")
    task_name = st.text_input("Task")

    # Add category selection
    category = st.selectbox("Category", CATEGORIES)

    # Add Work flag checkbox
    is_work = st.checkbox("Is this a work task?",  help='Work tasks are automatically hidden in Weekend Mode.')

    col1, col2 = st.columns(2)
    with col1:
        difficulty = st.slider("Difficulty", 1, 10, 5)
    with col2:
        urgency = st.slider('Base Urgency', 1, 10, 5)

    if has_deadline:
        col_ideal, col_due, col_start = st.columns(3)
        with col_due:
            due_date = st.date_input("Hard Deadline")
            due_date_str = due_date.isoformat()
        with col_ideal:
            if has_ideal:
                ideal_date = st.date_input("Ideal Deadline")
                ideal_date_str = ideal_date.isoformat()
        with col_start:
            if has_start:
                start_date = st.date_input("Start Date")
                start_date_str = start_date.isoformat()

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
            "Partial_Done": False,
            "Category": category,
            "Task": task_name,
            "Difficulty": difficulty,
            "Urgency": urgency,
            "Base_Urgency": urgency,
            "Due_Date": due_date_str,
            "Ideal_Due_Date": ideal_date_str,
            "Start_Date": start_date_str,
            "Creation_Date": datetime.now(timezone).strftime('%Y-%m-%d'),
            "Target": target,
            "Roll": adjusted_roll,
            "Status": status,
            "_Sort_Key": random.random(), # Generated ONCE per task
            "Is_Recurring": is_recurring,
            "Interval_Least": interval_least,
            "Interval_Average": interval_average,
            "Interval_Max": interval_max,
            "Last_Completed_Date": None,
            "Is_Work": is_work,
            "Is_Important": is_important
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
            ["None (Default)", "Category", "Status", "Urgency", "Task Name", "Due_Date"]
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
            "Task", "Category", "Is_Work", "Is_Important", "Status", "Done", "Partial_Done",
            "Difficulty", "Urgency", "Base_Urgency", "Due_Date", "Ideal_Due_Date", "Start_Date", "Creation_Date", "Target", "Roll",
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
    # Safely initialize missing keys for all tasks
    for task in st.session_state.tasks:
         if "Partial_Done" not in task or pd.isna(task.get('Partial_Done')):
             task['Partial_Done'] = False
         if "Is_Work" not in task or pd.isna(task.get('Is_Work')):
            task['Is_Work'] = False
         if "Base_Urgency" not in task:
             task['Base_Urgency'] = task.get('Urgency', 5)
         if "Due_Date" not in task:
             task['Due_Date'] = None
         if "Ideal_Due_Date" not in task:
             task['Ideal_Due_Date'] = None
         if "Start_Date" not in task:
             task["Start_Date"] = None
         if 'Is_Important' not in task or pd.isna(task.get('Is_Important')):
             task['Is_Important'] = False
         if "Creation_Date" not in task:
             task['Creation_Date'] = datetime.now(timezone).strftime('%Y-%m-%d')

    # Convert master list to a Pandas DataFrame for easy filtering
    df = pd.DataFrame(st.session_state.tasks)

    # Convert string dates to real datetime objects
    if 'Due_Date' in df.columns:
        df['Due_Date'] = pd.to_datetime(df['Due_Date']).dt.date
    if 'Start_Date' in df.columns:
        df['Start_Date'] = pd.to_datetime(df['Start_Date']).dt.date

    # Calculate synthetic due dates for recurring tasks
    if 'Is_Recurring' in df.columns:
        # Create safe temporary dates for the math
        df['Temp_Last'] = pd.to_datetime(df.get('Last_Completed_Date')).dt.date
        df['Temp_Creation'] = pd.to_datetime(df.get('Creation_Date', datetime.now(timezone).date())).dt.date

        def calculate_recurring_due(row):
            # Only apply this math to recurring tasks
            if row.get('Is_Recurring'):
                # If it's never been done, base it on when the task was created
                base_date = row['Temp_Last'] if pd.notna(row['Temp_Last']) else row['Temp_Creation']
                interval = row.get('Interval_Average', 1)

                if pd.notna(base_date) and pd.notna(interval):
                    return base_date + timedelta(days=int(interval))

            # For non-recurring tasks, just return their normal due date
            return row.get('Due_Date')

        # Apply the math and overwrite the due_date column purely for the UI
        df['Due_Date'] = df.apply(calculate_recurring_due, axis=1)

        # Clean up the temporary columns
        df = df.drop(columns=['Temp_Last', 'Temp_Creation'])

    st.write("---")

    if weekend_mode:
        st.write('### 🌴 Weekend Mode (All Quests)')
        current_category = 'Weekend'

        # Global reroll button
        if st.button('🔄 Reroll ALL Quests', key='reroll_all'):
            process_recurring_tasks(st.session_state.tasks)
            process_deadline_tasks(st.session_state.tasks)
            for task in st.session_state.tasks:
                if task['Status'] in ['Active', 'Skipped', 'Partial']:
                    task['Done'] = False
                    task['Partial_Done'] = False
                    task['_Sort_Key'] = random.random()
                    success, base_roll, adjusted_roll, target = roll_for_task(
                        task['Difficulty'], task['Urgency'], battery
                    )
                    task['Roll'] = adjusted_roll
                    task['Target'] = target
                    task['Status'] = 'Active' if success else 'Skipped'
            save_tasks(st.session_state.tasks)
            st.rerun()

        # Skip category filtering and use the whole dataframe
        cat_df = df[df['Is_Work'] == False]

    else: # Normal mode
        # Category selector - remembers selection across reruns
        current_category = st.radio(
            "Select Category",
            options=CATEGORIES,
            horizontal=True,
            label_visibility='collapsed', # hides title so it looks like clean tab bar
            key='active_tab_memory' # magic key to remember spot
        )

        # Use columns to put the header and reroll button on the same line
        col_head, col_btn = st.columns([3, 1])
        with col_head:
            st.write(f'### {current_category}')
        with col_btn:
            # Category-specific reroll button
            if st.button('🔄 Reroll Quests', key=f'reroll_{current_category}'):
                # Snapshot categories before they shift
                original_cats = {t['ID']: t.get('Category') for t in st.session_state.tasks}

                # Update dynamic urgencies BEFORE rerolling
                process_recurring_tasks(st.session_state.tasks)
                process_deadline_tasks(st.session_state.tasks)

                for task in st.session_state.tasks:
                    # Check if task belongs in this reroll sweep
                    was_here = original_cats.get(task['ID']) == current_category
                    is_here = task.get('Category') == current_category

                    # Scoop up anything that started here, or just arrived here
                    if (was_here or is_here) and task['Status'] in ['Active', 'Skipped', 'Partial']:
                        # Reset the checkmark and give a fresh sort key
                        task['Done'] = False
                        task['Partial_Done'] = False # reset the "partial" flag for a new roll
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
        st.info(f"No quests in to display yet.")

    else: # Skip the rest of the loop and move to the next tab
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

            # Calculate task hit % on the fly
            active_df["Hit %"] = active_df["Target"].apply(lambda t: calculate_hit_chance(t, battery))

            # Safety check to handle older tasks
            if 'Partial_Done' not in active_df.columns:
                active_df['Partial_Done'] = False

            # Capture the output of the data editor
            edited_active = st.data_editor(
                active_df,
                column_config={
                    "Done": st.column_config.CheckboxColumn("Done?", default=False, width='small'),
                    "Partial_Done": st.column_config.CheckboxColumn("Done for today?", default=False, width='small'),
                    "Due_Date": st.column_config.DateColumn("Due Date", format="MMM DD, YYYY"),
                    "Hit %": st.column_config.ProgressColumn(
                        "Hit Chance",
                        help="Probability of beating the Target DC at your current battery level.",
                        format="%d%%",
                        min_value=0,
                        max_value=100,
                        width='medium'
                    )
                },
                column_order=['Done', 'Partial_Done', 'Task', 'Due_Date', 'Difficulty', 'Hit %'], #only show these columns
                # Disable editing for everything except the "Done" checkbox
                disabled=['Task', 'Due_Date', 'Difficulty', 'Hit %'],
                hide_index=True,
                key=f'active_{"weekend" if weekend_mode else current_category}' # Keys must be unique!
            )

            # Check for differences in the "Done" column
            needs_rerun = False

            for _, row in edited_active.iterrows():
                task_id = row['ID']
                is_done = row['Done']
                is_partial = row.get('Partial_Done', False)

                # Find the specific task in session state and update it
                for task in st.session_state.tasks:
                    if task['ID'] == task_id:
                        if is_done and not task.get('Done'): # fully completed overrides everything
                            task['Done'] = True
                            task['Partial_Done'] = False
                            task['Status'] = 'Completed'
                            # Set the flag for toast / balloons
                            st.session_state.celebration = {'Task': task['Task'], 'Target': task['Target'], 'Difficulty': task['Difficulty']}
                            task['Last_Completed_Date'] = datetime.now(timezone).strftime('%Y-%m-%d')
                            needs_rerun = True
                        elif is_partial and not task.get('Partial_Done'):
                            task['Partial_Done'] = True
                            task['Status'] = 'Partial'
                            needs_rerun = True

            # Force a quick rerun to immediately reflect the completed status
            if needs_rerun:
                save_tasks(st.session_state.tasks)  # SAVE TO CLOUD
                st.rerun()

        else:
            st.info("🎉 Congratulations, all tasks have been cleared! 🎉")

        # --- PARTIAL TASKS (Done for today) --- #
        partial_df = cat_df[cat_df['Status'] == 'Partial'].copy().reset_index(drop=True)

        if not partial_df.empty:
            st.write('### ⛺ Resting (Done for Today)')

            edited_partial = st.data_editor(
                partial_df,
                column_config={
                    "Done": st.column_config.CheckboxColumn("Fully Done?", default=False, width='small'),
                    "Partial_Done": st.column_config.CheckboxColumn("Done for today?", default=False, width='small'),
                },
                column_order=['Done', 'Partial_Done', 'Task', 'Difficulty'],
                disabled=['Task', 'Difficulty'],
                hide_index=True,
                key=f'partial_{current_category}'
            )

            needs_rerun = False
            for _, row in edited_partial.iterrows():
                task_id = row['ID']
                is_done = row['Done']
                is_partial = row['Partial_Done']

                for task in st.session_state.tasks:
                    if task['ID'] == task_id:
                        if is_done: # If task is fully finished from resting state
                            task['Done'] = True
                            task['Partial_Done'] = False
                            task['Status'] = 'Completed'
                            st.session_state.celebration = {'Task': task['Task'],
                                                            'Target': task['Target'],
                                                            'Difficulty': task['Difficulty']}
                            task['Last_Completed_Date'] = datetime.now(timezone).strftime('%Y-%m-%d')
                            needs_rerun = True
                        elif not is_partial: # If accidentally clicked and need to send back
                            task['Partial_Done'] = False
                            task['Status'] = 'Active'
                            needs_rerun = True

            if needs_rerun:
                save_tasks(st.session_state.tasks)
                st.rerun()

        # --- COMPLETED TASKS ---
        completed_df = cat_df[cat_df['Status'] == 'Completed'].copy().reset_index(drop=True)
        if not completed_df.empty:
            st.write('### 🏆 Vanquished To-Dos')

            # Convert string dates into real datetime objects to calculate deltas
            completed_df['Date_Obj'] = pd.to_datetime(completed_df['Last_Completed_Date']).dt.date
            today_date = datetime.now(timezone).date()

            # Helper function to categorize age of completed task
            def categorize_date(task_date):
                if pd.isna(task_date):
                    return "Older / Unknown"

                delta = (today_date - task_date).days
                if delta == 0:
                    return "Today"
                elif delta == 1:
                    return "Yesterday"
                elif delta <= 7:
                    return "Last 7 days"
                elif delta <= 30:
                    return "Last 30 days"
                else:
                    return "Older / Unknown"

            # Apply helper function to categorize tasks
            completed_df['Time_Bucket'] = completed_df['Date_Obj'].apply(categorize_date)

            # Create sub-navigation menu (using radio to preserve state)
            time_filter = st.radio(
                "Filter History",
                options=["Today", "Yesterday", "Last 7 days", "Last 30 days", "Older / Unknown"],
                horizontal=True,
                label_visibility="collapsed",
                key=f'history_filter_{current_category}'
            )

            # Filter dataframe based on selected sub-tab and sort by date
            filtered_completed_df = completed_df[completed_df['Time_Bucket'] == time_filter].reset_index(drop=True)
            filtered_completed_df = filtered_completed_df.sort_values(by=['Last_Completed_Date'], ascending=[False]).reset_index(drop=True)

            if not filtered_completed_df.empty:
                edited_completed = st.data_editor(
                    filtered_completed_df,
                    column_order=['Task', 'Difficulty', 'Last_Completed_Date'],
                    disabled=['Task', 'Difficulty', 'Last_Completed_Date'],
                    hide_index=True,
                    key=f'completed_{current_category}_{time_filter}'
                )

                needs_rerun = False
                for _, row in edited_completed.iterrows():
                    task_id = row["ID"]
                    is_done = row["Done"]
                    for task in st.session_state.tasks:
                        if task["ID"] == task_id and task["Done"] != is_done:
                            task["Done"] = is_done
                            if not is_done:
                                task["Status"] = "Active"
                                task["Last_Completed_Date"] = None
                            needs_rerun = True

                # Force a quick rerun to immediately reflect the completed status
                if needs_rerun:
                    save_tasks(st.session_state.tasks)  # SAVE TO CLOUD
                    st.rerun()
            else:
                st.info(f'No tasks completed in this timeframe ({time_filter}).')

        # --- SKIPPED TASKS --- #
        st.write("### ⛺ The Backlog (Skipped)")
        skipped_df = cat_df[cat_df['Status'] == 'Skipped']
        skipped_df = skipped_df.sort_values(by=['Urgency', 'Difficulty'], ascending=[False, True])

        if not skipped_df.empty:
            # Calculate task hit % on the fly
            skipped_df["Hit %"] = skipped_df["Target"].apply(lambda t: calculate_hit_chance(t, battery))

            edited_skipped = st.data_editor(
                skipped_df,
                column_config={
                    'Done': st.column_config.CheckboxColumn("Done?", default=False, width='small'),
                    "Hit %": st.column_config.ProgressColumn(
                        "Hit Chance",
                        help="Probability of beating the Target DC at your current battery level.",
                        format="%d%%",
                        min_value=0,
                        max_value=100,
                        width='medium'
                    )
                },
                column_order=['Done', 'Task', 'Difficulty', 'Hit %'],
                disabled=['Task', 'Difficulty', 'Hit %'],
                hide_index=True,
                key=f'skipped_{current_category}'
            )

            needs_rerun = False
            for _, row in edited_skipped.iterrows():  # (And edited_skipped.iterrows())
                task_id = row["ID"]
                is_done = row["Done"]
                for task in st.session_state.tasks:
                    if task["ID"] == task_id and task["Done"] != is_done:
                        task["Done"] = is_done
                        if is_done:
                            task["Status"] = "Completed"
                            st.session_state.celebration = {"Task": task["Task"], "Target": task["Target"],
                                                            "Difficulty": task['Difficulty']}
                            task["Last_Completed_Date"] = datetime.now(timezone).strftime("%Y-%m-%d")

                        needs_rerun = True

            # Force a quick rerun to immediately reflect the completed status
            if needs_rerun:
                save_tasks(st.session_state.tasks)  # SAVE TO CLOUD
                st.rerun()
        else:
            st.info("Your backlog is clear.")


        # --- UPCOMING & DORMANT TASKS --- #
        st.write("---")
        with st.expander("💤 Upcoming & Dormant Quests"):
            # Filter to only show Dormant tasks for the current view
            dormant_df = cat_df[cat_df['Status'] == 'Dormant'].copy().reset_index(drop=True)

            if not dormant_df.empty:
                # Helper function to explain *why* the task is sleeping
                def get_dormant_reason(row):
                    today_date = datetime.now(timezone).date()

                    # Safely check for future start dates using pd.notna
                    if pd.notna(row.get('Start_Date')) and row['Start_Date'] > today_date:
                        return f"Starts {row['Start_Date'].strftime('%b %d')}"

                    # Handle recurring "cooldowns", using synthetic due date
                    elif row.get('Is_Recurring'):
                        if pd.notna(row.get('Due_Date')):
                            return "On Cooldown"

                    return "Sleeping"

                # Apply the helder function to create a new readable column
                dormant_df['Status / Reason'] = dormant_df.apply(get_dormant_reason, axis=1)

                # Using dataframe instead of data_editor since these shouldn't be edited
                st.dataframe(
                    dormant_df,
                    column_config={
                        'Due_Date': st.column_config.DateColumn("Due Date", format="MMM DD, YYYY")
                    },
                    column_order=['Task', 'Status / Reason', 'Due_Date', 'Difficulty', 'Base_Urgency'],
                    hide_index=True,
                    use_container_width=True
                )
            else:
                st.info("No tasks are currently sleeping here. ")
else:
    st.write("---")
    st.info("Fill out the form above to start building your Quest Board!")