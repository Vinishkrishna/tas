from flask import Flask, render_template, request, jsonify
from data import employees, parts
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

# --- Configuration ---
# Use /tmp for writable files on Vercel (serverless environment)
IS_VERCEL = os.environ.get('VERCEL', False)
BASE_PATH = '/tmp' if IS_VERCEL else '.'

FILES = {
    'attendance': os.path.join(BASE_PATH, 'attendance_log.csv'),
    'production': os.path.join(BASE_PATH, 'production_log.csv'),
    'material': os.path.join(BASE_PATH, 'material_log.csv'),
    'standard_times': 'wp_data.csv'  # This is read-only, keep in root
}

# --- Helper: Init CSVs ---
def init_csvs():
    if not os.path.exists(FILES['attendance']):
        pd.DataFrame(columns=['date', 'shift', 'emp_id', 'present']).to_csv(FILES['attendance'], index=False)
    if not os.path.exists(FILES['production']):
        # plan_qty is Target, actual_qty is what they achieved
        pd.DataFrame(columns=['date', 'shift', 'part_id', 'work_area', 'plan_qty', 'actual_qty', 'efficiency']).to_csv(FILES['production'], index=False)
    if not os.path.exists(FILES['material']):
        pd.DataFrame(columns=['date', 'program', 'part_id', 'work_area', 'qty', 'req', 'actual', 'efficiency']).to_csv(FILES['material'], index=False)

init_csvs()

# --- Helper: Load Standard Times ---
# Assuming wp_data.csv has columns: [Part_ID, prefit, CCA, PAA, Paint_Booth, Autoclave]
try:
    wp_data = pd.read_csv(FILES['standard_times'])
    header = wp_data.columns.tolist() # e.g., ['Part_ID', 'prefit', ...]
except:
    wp_data = pd.DataFrame()
    header = []

@app.route("/")
def index():
    return render_template("index.html", employees=employees, parts=parts, header=header[1:])

# --- ATTENDANCE ---
@app.route("/mark_attendance", methods=["POST"])
def mark_attendance():
    data = request.get_json()
    date = data.pop('date')
    shift = data.pop('shift')
    
    new_rows = []
    for emp_id, present in data.items():
        new_rows.append({'date': date, 'shift': shift, 'emp_id': emp_id, 'present': present})
    
    df = pd.DataFrame(new_rows)
    
    # Append to CSV (in production, you might want to overwrite existing date/shift entries)
    # Here we simply append for log history
    if os.path.exists(FILES['attendance']):
        df.to_csv(FILES['attendance'], mode='a', header=False, index=False)
    else:
        df.to_csv(FILES['attendance'], index=False)
        
    return jsonify({"status": "success", "count": len(new_rows)})

@app.route("/get_attendance", methods=["GET"])
def get_attendance():
    date = request.args.get('date')
    shift = request.args.get('shift')
    
    if not os.path.exists(FILES['attendance']):
        return jsonify({})

    df = pd.read_csv(FILES['attendance'])
    # Filter for specific date/shift
    mask = (df['date'] == date) & (df['shift'] == shift)
    filtered = df[mask]
    
    # Convert to dict {emp_id: true/false}
    attendance_dict = dict(zip(filtered.emp_id, filtered.present))
    return jsonify(attendance_dict)

# --- PRODUCTION PLAN & SAVING ---
@app.route("/plan_production", methods=["POST"])
def plan_production():
    data = request.get_json()
    selected_parts = data["parts"]
    date = data['date']
    shift = data['shift']

    # 1. Calculate Assignments (Logic from previous step)
    # Fetch available employees
    att_df = pd.read_csv(FILES['attendance'])
    present_ids = att_df[(att_df['date'] == date) & (att_df['shift'] == shift) & (att_df['present'] == True)]['emp_id'].tolist()
    
    present_employees = [
        {"id": eid, "name": emp["name"], "efficiency": emp["efficiency"], "trained_skills": emp["trained_skills"]}
        for eid, emp in employees.items() if eid in present_ids
    ]
    present_employees.sort(key=lambda x: x["efficiency"], reverse=True)

    # ... (Your existing assignment logic here) ...
    # Simplified for brevity:
    assignments = []
    log_entries = []
    
    for item in selected_parts:
        part_id = item["part_id"]
        qty = int(item["quantity"])
        area = item["work_area"]
        part_name = parts[part_id]['name']

        # Determine operators (simplified placeholder logic)
        ops = []
        if present_employees:
            ops.append({"best_operator": present_employees[0]['name'], "support_operator": "None"})

        assignments.append({
            "part": part_name,
            "part_id": part_id,
            "quantity": qty,
            "work_area": area,
            "operators": ops
        })

        # Prepare data to save to DB
        log_entries.append({
            'date': date,
            'shift': shift,
            'part_id': part_id,
            'work_area': area,
            'plan_qty': qty,
            'actual_qty': 0, # Starts at 0
            'efficiency': 0
        })

    # 2. Save Plan to CSV
    log_df = pd.DataFrame(log_entries)
    log_df.to_csv(FILES['production'], mode='a', header=not os.path.exists(FILES['production']), index=False)

    return jsonify({"assignments": assignments, "present_count": len(present_employees)})

@app.route("/update_production_actual", methods=["POST"])
def update_production_actual():
    # Called when user types in "Actual Quantity" box
    data = request.get_json()
    date = data['date']
    shift = data['shift']
    part_id = data['part_id']
    area = data['work_area']
    actual = float(data['actual'])
    plan = float(data['plan'])
    
    efficiency = (actual / plan * 100) if plan > 0 else 0

    # Update CSV using Pandas
    df = pd.read_csv(FILES['production'])
    
    # Find the row and update
    mask = (df['date'] == date) & (df['shift'] == shift) & (df['part_id'] == part_id) & (df['work_area'] == area)
    
    if mask.any():
        df.loc[mask, 'actual_qty'] = actual
        df.loc[mask, 'efficiency'] = efficiency
        df.to_csv(FILES['production'], index=False)
        return jsonify({"status": "updated", "efficiency": efficiency})
    
    return jsonify({"status": "not found"})

# --- MATERIAL ---
@app.route("/save_material", methods=["POST"])
def save_material():
    data = request.get_json()
    date_str = data.get("date")
    materials = data.get("materials", [])
    
    rows = []
    for item in materials:
        rows.append({
            'date': date_str,
            'program': item['program'],
            'part_id': item['part_id'],
            'work_area': item['work_area'],
            'qty': item['qty'],
            'req': item['req'],
            'actual': item['actual'],
            'efficiency': float(item['efficiency'].replace('%',''))
        })
    
    df = pd.DataFrame(rows)
    df.to_csv(FILES['material'], mode='a', header=not os.path.exists(FILES['material']), index=False)
            
    return jsonify({"status": "success", "count": len(rows)})    

# --- DASHBOARD DATA AGGREGATION ---
@app.route("/get_dashboard_data")
def get_dashboard_data():
    # Default to today if no date provided, or filter by specific date
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    response_data = {}
    work_areas = ['Autoclave', 'CCA', 'PAA', 'Paint_Booth', 'Prefit']

    # 1. Load Data
    prod_df = pd.read_csv(FILES['production']) if os.path.exists(FILES['production']) else pd.DataFrame()
    mat_df = pd.read_csv(FILES['material']) if os.path.exists(FILES['material']) else pd.DataFrame()

    # 2. Filter by Date (Optional: remove this filter to show ALL TIME average)
    if not prod_df.empty:
        prod_df = prod_df[prod_df['date'] == date]
    if not mat_df.empty:
        mat_df = mat_df[mat_df['date'] == date]

    # 3. Calculate Stats per Area
    for area in work_areas:
        # Handle naming mismatches (CSV might save 'Paint Booth' vs 'Paint_Booth')
        area_clean = area.replace('_', ' ').lower()
        
        prod_effs = []
        mat_effs = []

        # Get Production Efficiency for this area
        if not prod_df.empty:
            # Case insensitive match
            p_rows = prod_df[prod_df['work_area'].str.lower().str.replace('_', ' ') == area_clean]
            prod_effs = p_rows['efficiency'].tolist()

        # Get Material Efficiency for this area
        if not mat_df.empty:
            m_rows = mat_df[mat_df['work_area'].str.lower().str.replace('_', ' ') == area_clean]
            mat_effs = m_rows['efficiency'].tolist()

        # Combine
        all_effs = prod_effs + mat_effs
        avg_eff = sum(all_effs) / len(all_effs) if all_effs else 0
        
        response_data[area] = avg_eff

    return jsonify(response_data)

# Required for Vercel deployment
application = app

if __name__ == "__main__":
    app.run(debug=True)