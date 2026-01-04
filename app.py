from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_bcrypt import Bcrypt
from flask_mysqldb import MySQL
import MySQLdb.cursors
import datetime
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

bcrypt = Bcrypt(app)
mysql = MySQL(app)

# ---------- Helper: login required ----------
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/home')
def home():
    return render_template('home.html')

@app.route('/about')
def about_page():
    return render_template('about.html')


# ---------- Routes ----------
@app.route('/')
def index():
    if "user_id" in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

# Register
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        # check existing
        cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cursor.fetchone():
            flash('Email already registered', 'danger')
            return redirect(url_for('register'))
        pw_hash = bcrypt.generate_password_hash(password).decode('utf-8')
        cursor.execute("INSERT INTO users (name,email,password_hash) VALUES (%s,%s,%s)", (name,email,pw_hash))
        mysql.connection.commit()
        flash('Registration successful. Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

# Login
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()
        if user and bcrypt.check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Dashboard - shows user's trips and recent trips
@app.route('/dashboard')
@login_required
def dashboard():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    # user created trips
    cursor.execute("SELECT * FROM trips WHERE creator_id=%s ORDER BY start_datetime ASC", (session['user_id'],))
    my_trips = cursor.fetchall()
    # upcoming public trips from others
    cursor.execute("SELECT t.*, u.name as creator_name FROM trips t JOIN users u ON t.creator_id=u.id WHERE t.creator_id!=%s ORDER BY t.start_datetime ASC LIMIT 10", (session['user_id'],))
    other_trips = cursor.fetchall()
    return render_template('dashboard.html', my_trips=my_trips, other_trips=other_trips)

# Create trip
@app.route('/create_trip', methods=['GET','POST'])
@login_required
def create_trip():
    if request.method == 'POST':
        title = request.form.get('title') or ''
        destination = request.form['destination']
        details = request.form.get('details','')
        start_dt = request.form['start_datetime']
        transport = request.form.get('transport','')
        max_people = int(request.form.get('max_people') or 5)
        # parse datetime
        try:
            dt = datetime.datetime.fromisoformat(start_dt)
        except:
            flash('Invalid datetime format. Use YYYY-MM-DDTHH:MM', 'danger')
            return redirect(url_for('create_trip'))
        cursor = mysql.connection.cursor()
        cursor.execute("INSERT INTO trips (creator_id,title,destination,details,start_datetime,transport,max_people) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                       (session['user_id'], title, destination, details, dt, transport, max_people))
        mysql.connection.commit()
        flash('Trip created!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('create_trip.html')

# View trip and join
@app.route('/trip/<int:trip_id>')
@login_required
def trip(trip_id):
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT t.*, u.name as creator_name FROM trips t JOIN users u ON t.creator_id=u.id WHERE t.id=%s", (trip_id,))
    trip = cursor.fetchone()
    if not trip:
        flash('Trip not found', 'danger')
        return redirect(url_for('dashboard'))
    cursor.execute("SELECT u.id, u.name FROM trip_participants p JOIN users u ON p.user_id=u.id WHERE p.trip_id=%s", (trip_id,))
    participants = cursor.fetchall()
    # check is joined
    cursor.execute("SELECT 1 FROM trip_participants WHERE trip_id=%s AND user_id=%s", (trip_id, session['user_id']))
    joined = cursor.fetchone() is not None
    return render_template('trip.html', trip=trip, participants=participants, joined=joined)

@app.route('/join_trip/<int:trip_id>', methods=['POST'])
@login_required
def join_trip(trip_id):
    cursor = mysql.connection.cursor()
    # ensure not already joined
    try:
        cursor.execute("INSERT INTO trip_participants (trip_id,user_id) VALUES (%s,%s)", (trip_id, session['user_id']))
        mysql.connection.commit()
        flash('You joined the trip', 'success')
    except Exception as e:
        flash('Could not join (maybe already joined)', 'warning')
    return redirect(url_for('trip', trip_id=trip_id))

# Search buddies / trips by destination or city
@app.route('/search', methods=['GET','POST'])
@login_required
def search():
    results = []
    query = ''
    if request.method == 'POST':
        query = request.form.get('query','').strip()
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        # search trips by destination or title
        cursor.execute("SELECT t.*, u.name AS creator_name FROM trips t JOIN users u ON t.creator_id=u.id WHERE (destination LIKE %s OR title LIKE %s) ORDER BY start_datetime ASC",
                       (f"%{query}%", f"%{query}%"))
        results = cursor.fetchall()
    return render_template('search.html', results=results, query=query)

# Simple chat APIs (fetch/post) for a trip
@app.route('/messages/<int:trip_id>', methods=['GET'])
@login_required
def get_messages(trip_id):
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT m.*, u.name as sender_name FROM messages m JOIN users u ON m.sender_id=u.id WHERE trip_id=%s ORDER BY sent_at ASC", (trip_id,))
    msgs = cursor.fetchall()
    return jsonify(msgs)

@app.route('/messages/<int:trip_id>', methods=['POST'])
@login_required
def post_message(trip_id):
    data = request.get_json()
    content = data.get('content','').strip()
    if not content:
        return jsonify({'error':'empty'}), 400
    cursor = mysql.connection.cursor()
    cursor.execute("INSERT INTO messages (trip_id, sender_id, content) VALUES (%s,%s,%s)", (trip_id, session['user_id'], content))
    mysql.connection.commit()
    return jsonify({'ok':True}), 201

# Profile edit (simple)
@app.route('/profile', methods=['GET','POST'])
@login_required
def profile():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    if request.method == 'POST':
        name = request.form['name']
        city = request.form['city']
        cursor.execute("UPDATE users SET name=%s, city=%s WHERE id=%s", (name, city, session['user_id']))
        mysql.connection.commit()
        session['user_name'] = name
        flash('Profile updated', 'success')
        return redirect(url_for('profile'))
    cursor.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
    user = cursor.fetchone()
    return render_template('profile.html', user=user)

if __name__ == '__main__':
    app.secret_key = app.config['SECRET_KEY']
    app.run(debug=True)
