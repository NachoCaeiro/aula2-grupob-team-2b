import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from fpdf import FPDF

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_very_secret_key_here'  # Change this in a real application!

DB_NAME = "database/clinic.db"

def get_db_connection():
    """Creates a database connection."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row # This allows accessing columns by name
    return conn

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT,
        phone TEXT,
        email TEXT UNIQUE NOT NULL
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        surname TEXT NOT NULL,
        document_number TEXT UNIQUE NOT NULL,
        phone TEXT,
        email TEXT,
        age INTEGER,
        company_id INTEGER,
        FOREIGN KEY (company_id) REFERENCES Companies(id)
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS MedicalRecords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL,
        diagnosis TEXT NOT NULL,
        date TEXT NOT NULL,
        company_id INTEGER NOT NULL,
        FOREIGN KEY (patient_id) REFERENCES Patients(id),
        FOREIGN KEY (company_id) REFERENCES Companies(id)
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()
    print(f"Database '{DB_NAME}' initialized successfully.")

def add_default_user():
    """Adds a default user to the database if they don't already exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    username = "Juan Pablo Moya"
    # Check if user already exists
    cursor.execute("SELECT id FROM Users WHERE username = ?", (username,))
    user = cursor.fetchone()

    if user is None:
        password = "Victoria2024"
        password_hash = generate_password_hash(password)
        try:
            cursor.execute("INSERT INTO Users (username, password_hash) VALUES (?, ?)", (username, password_hash))
            conn.commit()
            print(f"User '{username}' created successfully.")
        except sqlite3.IntegrityError:
            print(f"User '{username}' already exists (caught by IntegrityError).") # Should not happen due to previous check
    else:
        print(f"User '{username}' already exists.")
    conn.close()

# Decorator for login required
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            # next_page = request.args.get('next') # Not using next for now, simple redirect to home
            return redirect(url_for('home'))
        else:
            error = 'Invalid username or password. Please try again.'

    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def home():
    conn = get_db_connection()
    cursor = conn.cursor()

    search_company_name = request.args.get('search_company_name', '').strip()
    search_patient_document = request.args.get('search_patient_document', '').strip()

    selected_patient = None
    medical_history = []

    # Base query for companies
    company_query = "SELECT id, name, address, phone, email FROM Companies"
    company_params = []
    if search_company_name:
        company_query += " WHERE name LIKE ?"
        company_params.append(f"%{search_company_name}%")
    company_query += " ORDER BY name"
    cursor.execute(company_query, company_params)
    companies = cursor.fetchall()

    # Patient search and medical history
    if search_patient_document:
        cursor.execute("""
            SELECT p.id, p.name, p.surname, p.document_number, p.phone, p.email, p.age, p.company_id, c.name as company_name
            FROM Patients p
            LEFT JOIN Companies c ON p.company_id = c.id
            WHERE p.document_number = ?
        """, (search_patient_document,))
        selected_patient = cursor.fetchone()

        if selected_patient:
            cursor.execute("""
                SELECT mr.id, mr.diagnosis, mr.date, c.name as company_name
                FROM MedicalRecords mr
                JOIN Companies c ON mr.company_id = c.id
                WHERE mr.patient_id = ?
                ORDER BY mr.date DESC
            """, (selected_patient['id'],))
            medical_history = cursor.fetchall()
        # else: Optionally flash("Patient not found")

    # Fetch all patients or filter by company if company search is active
    # For simplicity, if a patient is selected by document, we might not need to list all other patients,
    # but for now, we'll list patients based on company search or all if no company search.
    patient_query = """
        SELECT p.id, p.name, p.surname, p.document_number, p.phone, p.email, p.age, p.company_id, c.name as company_name
        FROM Patients p
        LEFT JOIN Companies c ON p.company_id = c.id
    """
    patient_params = []
    if search_company_name:
        # Get IDs of companies that match the search
        matching_company_ids = [c['id'] for c in companies]
        if matching_company_ids:
            placeholders = ','.join('?' * len(matching_company_ids))
            patient_query += f" WHERE p.company_id IN ({placeholders})"
            patient_params.extend(matching_company_ids)
        else: # No company matched, so no patients will be listed from this filter
            patient_query += " WHERE 1=0"

    patient_query += " ORDER BY p.surname, p.name"
    cursor.execute(patient_query, patient_params)
    patients = cursor.fetchall()

    conn.close()
    return render_template('dashboard.html',
                           companies=companies,
                           patients=patients,
                           selected_patient=selected_patient,
                           medical_history=medical_history,
                           search_company_name_value=search_company_name,
                           search_patient_document_value=search_patient_document)

# Placeholder routes for buttons in dashboard
@app.route('/add_company', methods=['GET', 'POST'])
@login_required
def add_company():
    if request.method == 'POST':
        name = request.form['name']
        address = request.form['address']
        phone = request.form['phone']
        email = request.form['email']

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO Companies (name, address, phone, email) VALUES (?, ?, ?, ?)",
                           (name, address, phone, email))
            conn.commit()
        except sqlite3.IntegrityError:
            # Handle email uniqueness error if necessary, though form validation should catch it
            conn.rollback() # Rollback on error
            # You might want to flash a message here
            return "Error: Email already exists.", 400
        finally:
            conn.close()
        return redirect(url_for('home'))

    # For GET request, provide the correct action URL for the form
    return render_template('company_form.html', form_action_url=url_for('add_company'))

@app.route('/edit_company/<int:company_id>', methods=['GET', 'POST'])
@login_required
def edit_company(company_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        address = request.form['address']
        phone = request.form['phone']
        email = request.form['email']

        try:
            cursor.execute("UPDATE Companies SET name = ?, address = ?, phone = ?, email = ? WHERE id = ?",
                           (name, address, phone, email, company_id))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            # You might want to flash a message here
            return "Error: Email already exists for another company.", 400
        finally:
            conn.close()
        return redirect(url_for('home'))

    # GET request: Fetch company data
    cursor.execute("SELECT id, name, address, phone, email FROM Companies WHERE id = ?", (company_id,))
    company = cursor.fetchone()
    conn.close()

    if company is None:
        return "Company not found", 404

    return render_template('company_form.html', company=company, form_action_url=url_for('edit_company', company_id=company_id))

@app.route('/delete_company/<int:company_id>', methods=['POST'])
@login_required
def delete_company(company_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Get patient_ids associated with the company
        cursor.execute("SELECT id FROM Patients WHERE company_id = ?", (company_id,))
        patient_ids_tuples = cursor.fetchall()
        patient_ids = [pt[0] for pt in patient_ids_tuples]

        # Delete medical records for those patients
        if patient_ids:
            placeholders = ','.join('?' for _ in patient_ids)
            cursor.execute(f"DELETE FROM MedicalRecords WHERE patient_id IN ({placeholders})", patient_ids)

        # Delete patients associated with the company
        cursor.execute("DELETE FROM Patients WHERE company_id = ?", (company_id,))

        # Delete the company itself
        cursor.execute("DELETE FROM Companies WHERE id = ?", (company_id,))

        conn.commit()
    except Exception as e:
        conn.rollback()
        # Log the error e
        return "Error deleting company and associated data.", 500
    finally:
        conn.close()
    return redirect(url_for('home'))

@app.route('/add_patient', methods=['GET', 'POST'])
@login_required
def add_patient():
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        surname = request.form['surname']
        document_number = request.form['document_number']
        phone = request.form.get('phone')
        email = request.form.get('email')
        age_str = request.form.get('age')
        age = int(age_str) if age_str and age_str.isdigit() else None
        company_id_str = request.form.get('company_id')
        company_id = int(company_id_str) if company_id_str and company_id_str.isdigit() else None

        if not company_id:
            cursor.execute("SELECT id, name FROM Companies ORDER BY name")
            companies_for_form = cursor.fetchall()
            conn.close()
            return render_template('patient_form.html',
                                   form_action_url=url_for('add_patient'),
                                   companies=companies_for_form,
                                   error="Company must be selected.",
                                   patient=request.form) # Pass back form data

        try:
            cursor.execute("""
                INSERT INTO Patients (name, surname, document_number, phone, email, age, company_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, surname, document_number, phone, email, age, company_id))
            conn.commit()
        except sqlite3.IntegrityError as e:
            conn.rollback()
            error_message = "An integrity error occurred. Please check your input."
            if "UNIQUE constraint failed: Patients.document_number" in str(e):
                error_message = "Document number already exists."

            cursor.execute("SELECT id, name FROM Companies ORDER BY name")
            companies_for_form = cursor.fetchall()
            conn.close()
            return render_template('patient_form.html',
                                   form_action_url=url_for('add_patient'),
                                   companies=companies_for_form,
                                   error=error_message,
                                   patient=request.form) # Pass back form data
        finally:
            if conn:
                conn.close()
        return redirect(url_for('home'))

    # GET request
    cursor.execute("SELECT id, name FROM Companies ORDER BY name")
    companies = cursor.fetchall()
    conn.close()
    return render_template('patient_form.html', companies=companies, form_action_url=url_for('add_patient'))

@app.route('/edit_patient/<int:patient_id>', methods=['GET', 'POST'])
@login_required
def edit_patient(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        surname = request.form['surname']
        document_number = request.form['document_number']
        phone = request.form.get('phone')
        email = request.form.get('email')
        age_str = request.form.get('age')
        age = int(age_str) if age_str and age_str.isdigit() else None
        company_id_str = request.form.get('company_id')
        company_id = int(company_id_str) if company_id_str and company_id_str.isdigit() else None

        if not company_id:
            cursor.execute("SELECT id, name FROM Companies ORDER BY name")
            companies_for_form = cursor.fetchall()
            # Fetch patient data again for the form
            cursor.execute("SELECT * FROM Patients WHERE id = ?", (patient_id,))
            patient_data = cursor.fetchone() # This will be a Row object
            conn.close()
            # Create a dictionary from request.form and update with patient_id for template
            current_form_data = dict(request.form)
            current_form_data['id'] = patient_id # ensure patient.id is available for url_for in template
            return render_template('patient_form.html',
                                   patient=current_form_data, # Pass current (failed) form data
                                   companies=companies_for_form,
                                   form_action_url=url_for('edit_patient', patient_id=patient_id),
                                   error="Company must be selected.")
        try:
            cursor.execute("""
                UPDATE Patients
                SET name = ?, surname = ?, document_number = ?, phone = ?, email = ?, age = ?, company_id = ?
                WHERE id = ?
            """, (name, surname, document_number, phone, email, age, company_id, patient_id))
            conn.commit()
        except sqlite3.IntegrityError as e:
            conn.rollback()
            error_message = "An integrity error occurred. Please check your input."
            if "UNIQUE constraint failed: Patients.document_number" in str(e):
                error_message = "Document number already exists for another patient."

            cursor.execute("SELECT id, name FROM Companies ORDER BY name")
            companies_for_form = cursor.fetchall()
            # Create a dictionary from request.form and update with patient_id for template
            current_form_data = dict(request.form)
            current_form_data['id'] = patient_id
            conn.close()
            return render_template('patient_form.html',
                                   patient=current_form_data, # Pass current (failed) form data
                                   companies=companies_for_form,
                                   form_action_url=url_for('edit_patient', patient_id=patient_id),
                                   error=error_message)
        finally:
            if conn:
                conn.close()
        return redirect(url_for('home'))

    # GET request
    cursor.execute("SELECT id, name, surname, document_number, phone, email, age, company_id FROM Patients WHERE id = ?", (patient_id,))
    patient = cursor.fetchone() # This is a Row object

    if patient is None:
        conn.close()
        return "Patient not found", 404

    cursor.execute("SELECT id, name FROM Companies ORDER BY name")
    companies = cursor.fetchall()
    conn.close()

    return render_template('patient_form.html', patient=patient, companies=companies, form_action_url=url_for('edit_patient', patient_id=patient_id))

@app.route('/delete_patient/<int:patient_id>', methods=['POST'])
@login_required
def delete_patient(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Delete associated medical records first
        cursor.execute("DELETE FROM MedicalRecords WHERE patient_id = ?", (patient_id,))
        # Then delete the patient
        cursor.execute("DELETE FROM Patients WHERE id = ?", (patient_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        # Log error e
        print(f"Error deleting patient: {e}") # For debugging
        return "Error deleting patient and associated records.", 500
    finally:
        conn.close()
    return redirect(url_for('home'))

# Helper function to get company_id for a patient
def get_patient_company_id(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT company_id FROM Patients WHERE id = ?", (patient_id,))
    result = cursor.fetchone()
    conn.close()
    return result['company_id'] if result else None

@app.route('/add_medical_record', methods=['GET', 'POST'])
@login_required
def add_medical_record(): # This is the general add medical record
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        patient_id_form = request.form.get('patient_id', type=int)
        diagnosis = request.form['diagnosis']
        date = request.form['date']

        if not patient_id_form:
            cursor.execute("SELECT id, name, surname, document_number FROM Patients ORDER BY surname, name")
            patients_for_form = cursor.fetchall()
            conn.close()
            return render_template('medical_record_form.html',
                                   patients=patients_for_form,
                                   form_action_url=url_for('add_medical_record'),
                                   error="Patient must be selected.",
                                   record_data=request.form) # Pass back form data as record_data

        company_id = get_patient_company_id(patient_id_form)
        if company_id is None:
             cursor.execute("SELECT id, name, surname, document_number FROM Patients ORDER BY surname, name")
             patients_for_form = cursor.fetchall()
             conn.close()
             return render_template('medical_record_form.html',
                                   patients=patients_for_form,
                                   form_action_url=url_for('add_medical_record'),
                                   error="Selected patient does not have an associated company.",
                                   record_data=request.form)

        try:
            cursor.execute("""
                INSERT INTO MedicalRecords (patient_id, diagnosis, date, company_id)
                VALUES (?, ?, ?, ?)
            """, (patient_id_form, diagnosis, date, company_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error adding medical record: {e}")
            cursor.execute("SELECT id, name, surname, document_number FROM Patients ORDER BY surname, name")
            patients_for_form = cursor.fetchall()
            conn.close()
            return render_template('medical_record_form.html',
                                   patients=patients_for_form,
                                   form_action_url=url_for('add_medical_record'),
                                   error=f"An error occurred: {e}",
                                   record_data=request.form)
        finally:
            if conn: conn.close()

        # Redirect to show the patient's history if possible
        patient_doc_num_cursor = get_db_connection().cursor()
        patient_doc_num_cursor.execute("SELECT document_number FROM Patients WHERE id = ?", (patient_id_form,))
        patient_doc_num_row = patient_doc_num_cursor.fetchone()
        patient_doc_num_cursor.connection.close()
        if patient_doc_num_row:
             return redirect(url_for('home', search_patient_document=patient_doc_num_row['document_number']))
        return redirect(url_for('home'))


    # GET request for general add_medical_record
    cursor.execute("SELECT id, name, surname, document_number FROM Patients ORDER BY surname, name")
    patients_data = cursor.fetchall()
    conn.close()
    return render_template('medical_record_form.html', patients=patients_data, form_action_url=url_for('add_medical_record'))


@app.route('/add_medical_record/<int:patient_id>', methods=['GET', 'POST'])
@login_required
def add_medical_record_for_patient(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.id, p.name, p.surname, p.document_number, p.company_id, c.name as company_name
        FROM Patients p
        LEFT JOIN Companies c ON p.company_id = c.id
        WHERE p.id = ?
    """, (patient_id,))
    patient = cursor.fetchone()

    if not patient:
        conn.close()
        # flash("Patient not found.")
        return redirect(url_for('home'))

    if request.method == 'POST':
        diagnosis = request.form['diagnosis']
        date = request.form['date']
        company_id = patient['company_id'] # Derived from the patient context

        if not company_id: # Should ideally not happen if patient data is consistent
            # flash("Selected patient does not have an associated company. Cannot add record.")
            # Re-render form with error
            conn.close()
            return render_template('medical_record_form.html',
                                   patient=patient, # Pass patient object
                                   company_name=patient['company_name'], # Pass company name
                                   form_action_url=url_for('add_medical_record_for_patient', patient_id=patient_id),
                                   error="Patient's company information is missing.")
        try:
            cursor.execute("""
                INSERT INTO MedicalRecords (patient_id, diagnosis, date, company_id)
                VALUES (?, ?, ?, ?)
            """, (patient_id, diagnosis, date, company_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error adding medical record for patient {patient_id}: {e}")
            # flash(f"An error occurred: {e}")
            conn.close()
            return render_template('medical_record_form.html',
                                   patient=patient,
                                   company_name=patient['company_name'],
                                   form_action_url=url_for('add_medical_record_for_patient', patient_id=patient_id),
                                   error=f"An error occurred: {e}",
                                   record_data=request.form) # Pass back current form data
        finally:
            if conn: conn.close()
        return redirect(url_for('home', search_patient_document=patient['document_number']))

    # GET request
    conn.close() # Already fetched patient, no more DB needed for GET
    return render_template('medical_record_form.html',
                           patient=patient, # Pass the specific patient
                           company_name=patient['company_name'], # Pass company name
                           form_action_url=url_for('add_medical_record_for_patient', patient_id=patient_id))


@app.route('/edit_medical_record/<int:record_id>', methods=['GET', 'POST'])
@login_required
def edit_medical_record(record_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        diagnosis = request.form['diagnosis']
        date = request.form['date']
        # patient_id and company_id are fixed for an existing record, taken from the record itself.

        cursor.execute("SELECT patient_id, company_id FROM MedicalRecords WHERE id = ?", (record_id,))
        original_record_ids = cursor.fetchone()
        if not original_record_ids:
             conn.close()
             return "Medical record not found", 404

        try:
            cursor.execute("""
                UPDATE MedicalRecords
                SET diagnosis = ?, date = ?
                WHERE id = ?
            """, (diagnosis, date, record_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            # Log error e
            print(f"Error updating medical record: {e}")
            # Fetch necessary data for rendering form again
            cursor.execute("SELECT mr.*, p.name as p_name, p.surname as p_surname, p.document_number as p_doc, c.name as c_name FROM MedicalRecords mr JOIN Patients p ON mr.patient_id = p.id JOIN Companies c ON mr.company_id = c.id WHERE mr.id = ?", (record_id,))
            record_data = cursor.fetchone()
            conn.close()
            if not record_data: return "Medical record not found", 404 # Should not happen

            patient_details = {'name': record_data['p_name'], 'surname': record_data['p_surname'], 'document_number': record_data['p_doc']}
            company_details = {'name': record_data['c_name']}

            return render_template('medical_record_form.html',
                                   record=record_data,
                                   patient_details=patient_details,
                                   company_details=company_details,
                                   form_action_url=url_for('edit_medical_record', record_id=record_id),
                                   error=f"An error occurred: {e}")
        finally:
            if conn:
                conn.close()
        return redirect(url_for('home')) # Or patient history view

    # GET request
    cursor.execute("""
        SELECT mr.id, mr.patient_id, mr.diagnosis, mr.date, mr.company_id,
               p.name as patient_name, p.surname as patient_surname, p.document_number as patient_document_number,
               c.name as company_name
        FROM MedicalRecords mr
        JOIN Patients p ON mr.patient_id = p.id
        LEFT JOIN Companies c ON mr.company_id = c.id
        WHERE mr.id = ?
    """, (record_id,))
    record = cursor.fetchone()
    conn.close()

    if record is None:
        return "Medical record not found", 404

    patient_details = {
        'name': record['patient_name'],
        'surname': record['patient_surname'],
        'document_number': record['patient_document_number']
    }
    company_details = {'name': record['company_name']}

    return render_template('medical_record_form.html',
                           record=record,
                           patient_details=patient_details,
                           company_details=company_details,
                           form_action_url=url_for('edit_medical_record', record_id=record_id))

@app.route('/delete_medical_record/<int:record_id>', methods=['POST'])
@login_required
def delete_medical_record(record_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM MedicalRecords WHERE id = ?", (record_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        # Log error e
        print(f"Error deleting medical record: {e}")
        return "Error deleting medical record.", 500
    finally:
        conn.close()
    return redirect(url_for('home'))

# PDF Generation Function
def generate_medical_record_pdf(record_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch Medical Record, Patient, and Company details
    query = """
        SELECT mr.id, mr.diagnosis, mr.date,
               p.name as patient_name, p.surname as patient_surname, p.document_number,
               c.name as company_name, c.email as company_email
        FROM MedicalRecords mr
        JOIN Patients p ON mr.patient_id = p.id
        JOIN Companies c ON mr.company_id = c.id
        WHERE mr.id = ?
    """
    cursor.execute(query, (record_id,))
    data = cursor.fetchone()
    conn.close()

    if not data:
        return None

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    # PDF Content
    pdf.cell(200, 10, txt=f"Dirigido a: {data['company_name']}", ln=1, align="L")
    pdf.ln(5) # Add spacing

    pdf.cell(200, 10, txt=f"Paciente: {data['patient_name']} {data['patient_surname']}", ln=1, align="L")
    pdf.cell(200, 10, txt=f"Documento: {data['document_number']}", ln=1, align="L")
    pdf.cell(200, 10, txt=f"Fecha de Atención: {data['date']}", ln=1, align="L")
    pdf.ln(5)

    pdf.set_font("Arial", 'B', size=12)
    pdf.cell(200, 10, txt="Diagnóstico:", ln=1, align="L")
    pdf.set_font("Arial", size=12)
    # Use multi_cell for diagnosis
    # Assuming diagnosis is stored as a single string. If it has newlines, FPDF handles them.
    # Width of cell, height of line, text, border (0 or 1), align ('L', 'C', 'R', 'J'), fill (boolean)
    pdf.multi_cell(0, 10, txt=data['diagnosis'], border=0, align="L")
    pdf.ln(10) # Add spacing after diagnosis

    pdf.cell(200, 10, txt="Firmado: Dr. Juan Pablo Moya", ln=1, align="L")

    # Output PDF as a byte string
    # dest='S' returns the document as a string (encoded in latin-1 by default by FPDF)
    # We need to encode it to latin-1 to get bytes, as Flask response expects bytes or unicode.
    return pdf.output(dest='S').encode('latin-1')

@app.route('/medical_record/<int:record_id>/pdf')
@login_required
def download_medical_record_pdf(record_id):
    pdf_content = generate_medical_record_pdf(record_id)
    if pdf_content:
        response = make_response(pdf_content)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=medical_record_{record_id}.pdf'
        return response
    else:
        # flash("Medical record not found or PDF generation failed.")
        return redirect(url_for('home'))


if __name__ == "__main__":
    init_db()
    add_default_user()
    # To run the Flask app:
    # 1. Make sure Flask is installed: pip install Flask
    # 2. Set environment variable: export FLASK_APP=app.py (Linux/macOS) or set FLASK_APP=app.py (Windows)
    # 3. Run: flask run
    # For development, you can also use: app.run(debug=True)
    # However, for this tool environment, we typically don't start a persistent server.
    # The print statement below is just for confirmation that the script runs.
    print("Flask app structure defined. To run, use 'flask run' after setting FLASK_APP.")
