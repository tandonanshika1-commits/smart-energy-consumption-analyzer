from flask import Flask, render_template, request, redirect, session, flash, Response
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
import random, csv, io
import numpy as np
from sklearn.linear_model import LinearRegression
from datetime import timedelta

app = Flask(__name__)
app.secret_key = "secret123"

def get_db():
    return psycopg2.connect(
        host="localhost",
        database="energy_db",
        user="postgres",
        password="1234"
    )

@app.route("/")
def home():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username=%s", (session["user"],))
    user_id = cursor.fetchone()[0]

    cursor.execute("SELECT id, name FROM appliances WHERE user_id=%s", (user_id,))
    appliances = cursor.fetchall()

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    if start_date and end_date:
        cursor.execute("""
            SELECT a.name, e.energy, TO_CHAR(e.time,'DD-MM-YYYY HH12:MI AM')
            FROM energy_usage e
            JOIN appliances a ON e.appliance_id=a.id
            WHERE e.user_id=%s
            AND DATE(e.time) BETWEEN %s AND %s
            ORDER BY e.time DESC
        """, (user_id, start_date, end_date))
    else:
        cursor.execute("""
            SELECT a.name, e.energy, TO_CHAR(e.time,'DD-MM-YYYY HH12:MI AM')
            FROM energy_usage e
            JOIN appliances a ON e.appliance_id=a.id
            WHERE e.user_id=%s
            ORDER BY e.time DESC
        """, (user_id,))

    energy_data = cursor.fetchall()

    # Daily data for trend graph
    cursor.execute("""
        SELECT DATE(e.time), SUM(e.energy)
        FROM energy_usage e
        WHERE e.user_id=%s
        GROUP BY DATE(e.time)
        ORDER BY DATE(e.time)
    """, (user_id,))
    daily_data = cursor.fetchall()

    trend_labels = [str(row[0]) for row in daily_data]
    trend_values = [float(row[1]) for row in daily_data]

    # Monthly data
    cursor.execute("""
        SELECT TO_CHAR(e.time, 'YYYY-MM'), SUM(e.energy)
        FROM energy_usage e
        WHERE e.user_id=%s
        GROUP BY TO_CHAR(e.time, 'YYYY-MM')
        ORDER BY TO_CHAR(e.time, 'YYYY-MM')
    """, (user_id,))
    monthly_data = cursor.fetchall()

    cursor.close()
    conn.close()

    total_usage = sum(float(r[1]) for r in energy_data) if energy_data else 0
    estimated_bill = round(total_usage * 6, 2)

    top_appliance = "N/A"
    if energy_data:
        top_appliance = max(energy_data, key=lambda x: float(x[1]))[0]

    suggestion = "✅ Energy usage is low. Good job!"

    if top_appliance == "AC":
        suggestion = "💡 AC is using the most energy. Set temperature to 24°C and turn it off when not needed."
    elif top_appliance == "fridge":
        suggestion = "💡 Fridge is using more energy. Avoid opening the fridge door again and again."
    elif top_appliance == "microwave":
        suggestion = "💡 Microwave usage is high. Use it only when needed."
    elif top_appliance == "Toaster":
        suggestion = "💡 Toaster usage is high. Try using it for shorter time."
    elif top_appliance == "fan":
        suggestion = "💡 Fan usage is high. Turn it off when leaving the room."
    elif top_appliance == "Light":
        suggestion = "💡 Light usage is high. Use LED bulbs and switch off lights in daylight."
    elif total_usage > 10:
        suggestion = "⚠️ Total energy usage is high. Please reduce unnecessary appliance usage."
    elif total_usage > 5:
        suggestion = "⚡ Total energy usage is moderate. Monitor high-energy appliances."

    chart_labels = []
    chart_values = []
    seen = {}

    for row in energy_data:
        if row[0] not in seen:
            seen[row[0]] = float(row[1])

    for k, v in seen.items():
        chart_labels.append(k)
        chart_values.append(v)

    chart_colors = [
        "#22c55e", "#f97316", "#ef4444", "#3b82f6",
        "#a855f7", "#eab308", "#14b8a6", "#ec4899"
    ]

    latest_time = energy_data[0][2] if energy_data else "No data yet"

    # Next usage prediction
    predicted_value = None
    if len(energy_data) > 2:
        y = np.array([float(row[1]) for row in energy_data])
        X = np.array(range(len(y))).reshape(-1, 1)

        model = LinearRegression()
        model.fit(X, y)

        predicted_value = round(float(model.predict([[len(y)]])[0]), 2)

    # Next day prediction
    predicted_day_value = None
    predicted_day_label = "Next Day"

    if len(trend_values) >= 3:
        X_day = np.array(range(len(trend_values))).reshape(-1, 1)
        y_day = np.array(trend_values)

        day_model = LinearRegression()
        day_model.fit(X_day, y_day)

        predicted_day_value = round(float(day_model.predict([[len(trend_values)]])[0]), 2)

        last_date = daily_data[-1][0]
        predicted_day_label = str(last_date + timedelta(days=1))

    # Next month prediction
    predicted_month_value = None
    monthly_values = [float(row[1]) for row in monthly_data]

    if len(monthly_values) >= 3:
        X_month = np.array(range(len(monthly_values))).reshape(-1, 1)
        y_month = np.array(monthly_values)

        month_model = LinearRegression()
        month_model.fit(X_month, y_month)

        predicted_month_value = round(float(month_model.predict([[len(monthly_values)]])[0]), 2)

    return render_template(
        "dashboard.html",
        username=session["user"],
        appliances=appliances,
        energy_data=energy_data,
        total_usage=round(total_usage, 2),
        estimated_bill=estimated_bill,
        total_appliances=len(appliances),
        top_appliance=top_appliance,
        suggestion=suggestion,
        chart_labels=chart_labels,
        chart_values=chart_values,
        chart_colors=chart_colors,
        latest_time=latest_time,
        start_date=start_date,
        end_date=end_date,
        predicted_value=predicted_value,
        predicted_day_value=predicted_day_value,
        predicted_day_label=predicted_day_label,
        predicted_month_value=predicted_month_value,
        trend_labels=trend_labels,
        trend_values=trend_values
    )

@app.route("/add-appliance", methods=["POST"])
def add_appliance():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username=%s", (session["user"],))
    user_id = cursor.fetchone()[0]

    name = request.form["name"]

    cursor.execute("INSERT INTO appliances (user_id,name) VALUES (%s,%s)", (user_id, name))
    conn.commit()

    cursor.close()
    conn.close()
    return redirect("/")

@app.route("/delete-appliance/<int:id>")
def delete_appliance(id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM energy_usage WHERE appliance_id=%s", (id,))
    cursor.execute("DELETE FROM appliances WHERE id=%s", (id,))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect("/")

@app.route("/generate-energy")
def generate():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username=%s", (session["user"],))
    user_id = cursor.fetchone()[0]

    cursor.execute("SELECT id FROM appliances WHERE user_id=%s", (user_id,))
    apps = cursor.fetchall()

    for a in apps:
        energy = round(random.uniform(0.5, 5), 2)
        cursor.execute(
            "INSERT INTO energy_usage (user_id,appliance_id,energy) VALUES (%s,%s,%s)",
            (user_id, a[0], energy)
        )

    conn.commit()
    cursor.close()
    conn.close()

    return redirect("/")

@app.route("/download")
def download():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username=%s", (session["user"],))
    user_id = cursor.fetchone()[0]

    cursor.execute("""
        SELECT a.name,e.energy,e.time
        FROM energy_usage e
        JOIN appliances a ON e.appliance_id=a.id
        WHERE e.user_id=%s
    """, (user_id,))
    data = cursor.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Appliance", "Energy", "Time"])

    for row in data:
        writer.writerow(row)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=data.csv"}
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user and check_password_hash(user[0], password):
            session["user"] = username
            return redirect("/")
        else:
            flash("Invalid login")

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username,password) VALUES (%s,%s)", (username, password))
        conn.commit()

        cursor.close()
        conn.close()

        return redirect("/login")

    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

app.run(debug=True)