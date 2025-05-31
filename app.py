import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, make_response, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from fpdf import FPDF
import smtplib
import ssl # For SMTP_SSL and STARTTLS
import socket # For gaierror
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import os
import sys

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_very_secret_key_here_CHANGE_ME' # Changed placeholder

# Determine base path for PyInstaller (running as bundle) or development
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    exe_dir = os.path.dirname(sys.executable)
    DB_DIR = os.path.join(exe_dir, 'database')
else:
    base_path = os.path.abspath(os.path.dirname(__file__))
    DB_DIR = os.path.join(base_path, 'database')

if not os.path.exists(DB_DIR):
    try:
        os.makedirs(DB_DIR)
        print(f"Directorio de base de datos creado en: {DB_DIR}")
    except Exception as e:
        print(f"Error creando directorio de base de datos en {DB_DIR}: {e}")

DB_PATH = os.path.join(DB_DIR, 'clinic.db')
print(f"Ruta de base de datos configurada a: {DB_PATH}")

# Email Configuration
SMTP_SERVER = 'smtp.example.com'
SMTP_PORT = 587
SMTP_USERNAME = 'your_email@example.com'
SMTP_PASSWORD = 'your_app_password'
EMAIL_SENDER = 'your_email@example.com'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db_directory = os.path.dirname(DB_PATH)
    if not os.path.exists(db_directory):
        try:
            os.makedirs(db_directory)
            # print(f"Directorio de base de datos asegurado en: {db_directory}") # Optional print
        except Exception as e:
            print(f"Error asegurando directorio de base de datos en {db_directory} dentro de init_db: {e}")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS Companies (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, address TEXT, phone TEXT, email TEXT UNIQUE NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS Patients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, surname TEXT NOT NULL, document_number TEXT UNIQUE NOT NULL, phone TEXT, email TEXT, age INTEGER, company_id INTEGER, FOREIGN KEY (company_id) REFERENCES Companies(id))")
    cursor.execute("CREATE TABLE IF NOT EXISTS MedicalRecords (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL, diagnosis TEXT NOT NULL, date TEXT NOT NULL, company_id INTEGER NOT NULL, FOREIGN KEY (patient_id) REFERENCES Patients(id), FOREIGN KEY (company_id) REFERENCES Companies(id))")
    cursor.execute("CREATE TABLE IF NOT EXISTS Users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)")
    conn.commit()
    conn.close()
    print(f"Base de datos '{DB_PATH}' inicializada exitosamente.")

def add_default_user():
    conn = get_db_connection()
    cursor = conn.cursor()
    username = "Juan Pablo Moya"
    cursor.execute("SELECT id FROM Users WHERE username = ?", (username,))
    user = cursor.fetchone()
    if user is None:
        password = "Victoria2024" # Consider a stronger default or removal for production
        password_hash = generate_password_hash(password)
        try:
            cursor.execute("INSERT INTO Users (username, password_hash) VALUES (?, ?)", (username, password_hash))
            conn.commit()
            print(f"Usuario '{username}' creado exitosamente.")
        except sqlite3.IntegrityError:
            print(f"Usuario '{username}' ya existe (detectado por IntegrityError).")
    else:
        print(f"Usuario '{username}' ya existe.")
    conn.close()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, inicie sesión para acceder a esta página.', 'info')
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
            flash('Inicio de sesión exitoso.', 'success')
            return redirect(url_for('home'))
        else:
            error = 'Usuario o contraseña incorrectos. Por favor, intente de nuevo.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada exitosamente.', 'info')
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
    company_query = "SELECT id, name, address, phone, email FROM Companies"
    company_params = []
    if search_company_name:
        company_query += " WHERE name LIKE ?"
        company_params.append(f"%{search_company_name}%")
    company_query += " ORDER BY name"
    cursor.execute(company_query, company_params)
    companies = cursor.fetchall()
    if search_patient_document:
        cursor.execute("SELECT p.*, c.name as company_name FROM Patients p LEFT JOIN Companies c ON p.company_id = c.id WHERE p.document_number = ?", (search_patient_document,))
        selected_patient = cursor.fetchone()
        if selected_patient:
            cursor.execute("SELECT mr.*, c.name as company_name FROM MedicalRecords mr JOIN Companies c ON mr.company_id = c.id WHERE mr.patient_id = ? ORDER BY mr.date DESC", (selected_patient['id'],))
            medical_history = cursor.fetchall()
        else:
            flash(f"Paciente con documento '{search_patient_document}' no encontrado.", 'warning')
    patient_query = "SELECT p.*, c.name as company_name FROM Patients p LEFT JOIN Companies c ON p.company_id = c.id"
    patient_params = []
    if search_company_name:
        matching_company_ids = [c['id'] for c in companies]
        if matching_company_ids:
            placeholders = ','.join('?' * len(matching_company_ids))
            patient_query += f" WHERE p.company_id IN ({placeholders})"
            patient_params.extend(matching_company_ids)
        else:
            patient_query += " WHERE 1=0"
    patient_query += " ORDER BY p.surname, p.name"
    cursor.execute(patient_query, patient_params)
    patients = cursor.fetchall()
    conn.close()
    return render_template('dashboard.html', companies=companies, patients=patients, selected_patient=selected_patient, medical_history=medical_history, search_company_name_value=search_company_name, search_patient_document_value=search_patient_document)

@app.route('/add_company', methods=['GET', 'POST'])
@login_required
def add_company():
    if request.method == 'POST':
        name = request.form['name']
        address = request.form['address']
        phone = request.form['phone']
        email = request.form['email']
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO Companies (name, address, phone, email) VALUES (?, ?, ?, ?)", (name, address, phone, email))
            conn.commit()
            flash('Empresa agregada exitosamente.', 'success')
        except sqlite3.IntegrityError:
            conn.rollback()
            flash('Error: El correo electrónico ya existe para otra empresa.', 'danger')
            return render_template('company_form.html', company=request.form, form_action_url=url_for('add_company'), error='El correo electrónico ya existe.'), 400
        finally:
            if conn: conn.close()
        return redirect(url_for('home'))
    return render_template('company_form.html', form_action_url=url_for('add_company'))

@app.route('/edit_company/<int:company_id>', methods=['GET', 'POST'])
@login_required
def edit_company(company_id):
    conn = get_db_connection()
    if request.method == 'POST':
        name = request.form['name']
        address = request.form['address']
        phone = request.form['phone']
        email = request.form['email']
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE Companies SET name = ?, address = ?, phone = ?, email = ? WHERE id = ?", (name, address, phone, email, company_id))
            conn.commit()
            flash('Empresa actualizada exitosamente.', 'success')
        except sqlite3.IntegrityError:
            conn.rollback()
            flash('Error: El correo electrónico ya existe para otra empresa.', 'danger')
            company_data_for_form = dict(request.form)
            company_data_for_form['id'] = company_id
            return render_template('company_form.html', company=company_data_for_form, form_action_url=url_for('edit_company', company_id=company_id), error='El correo electrónico ya existe.'), 400
        finally:
            if conn: conn.close()
        return redirect(url_for('home'))

    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Companies WHERE id = ?", (company_id,))
    company = cursor.fetchone()
    if conn: conn.close() # Close after fetch for GET

    if company is None:
        flash('Empresa no encontrada.', 'warning')
        return redirect(url_for('home'))
    return render_template('company_form.html', company=company, form_action_url=url_for('edit_company', company_id=company_id))

@app.route('/delete_company/<int:company_id>', methods=['POST'])
@login_required
def delete_company(company_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM Patients WHERE company_id = ?", (company_id,))
        patient_ids_tuples = cursor.fetchall()
        patient_ids = [pt[0] for pt in patient_ids_tuples]
        if patient_ids:
            placeholders = ','.join('?' * len(patient_ids))
            cursor.execute(f"DELETE FROM MedicalRecords WHERE patient_id IN ({placeholders})", patient_ids)
        cursor.execute("DELETE FROM Patients WHERE company_id = ?", (company_id,))
        cursor.execute("DELETE FROM Companies WHERE id = ?", (company_id,))
        conn.commit()
        flash('Empresa y todos sus pacientes y registros médicos asociados eliminados exitosamente.', 'success')
    except Exception as e:
        conn.rollback()
        print(f"Error al eliminar empresa: {e}")
        flash('Error al eliminar la empresa y sus datos asociados.', 'danger')
    finally:
        if conn: conn.close()
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
            flash('Error: La empresa debe ser seleccionada.', 'danger')
            companies_for_form = cursor.execute("SELECT id, name FROM Companies ORDER BY name").fetchall()
            # conn.close() # Keep open for companies_for_form
            return render_template('patient_form.html', form_action_url=url_for('add_patient'), companies=companies_for_form, error="La empresa debe ser seleccionada.", patient_data=request.form)
        try:
            cursor.execute("INSERT INTO Patients (name, surname, document_number, phone, email, age, company_id) VALUES (?, ?, ?, ?, ?, ?, ?)", (name, surname, document_number, phone, email, age, company_id))
            conn.commit()
            flash('Paciente agregado exitosamente.', 'success')
        except sqlite3.IntegrityError as e:
            conn.rollback()
            error_message = "Error de integridad. Verifique sus datos."
            if "UNIQUE constraint failed: Patients.document_number" in str(e):
                error_message = "El número de documento ya existe para otro paciente."
            flash(f'Error: {error_message}', 'danger')
            companies_for_form = cursor.execute("SELECT id, name FROM Companies ORDER BY name").fetchall()
            return render_template('patient_form.html', form_action_url=url_for('add_patient'), companies=companies_for_form, error=error_message, patient_data=request.form)
        finally:
            if conn: conn.close()
        return redirect(url_for('home'))

    companies_data = cursor.execute("SELECT id, name FROM Companies ORDER BY name").fetchall()
    if conn: conn.close()
    return render_template('patient_form.html', companies=companies_data, form_action_url=url_for('add_patient'))

@app.route('/edit_patient/<int:patient_id>', methods=['GET', 'POST'])
@login_required
def edit_patient(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor() # Define cursor early for broader scope
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
            flash('Error: La empresa debe ser seleccionada.', 'danger')
            companies_for_form = cursor.execute("SELECT id, name FROM Companies ORDER BY name").fetchall()
            current_form_data = dict(request.form)
            current_form_data['id'] = patient_id
            return render_template('patient_form.html', patient_data=current_form_data, companies=companies_for_form, form_action_url=url_for('edit_patient', patient_id=patient_id), error="La empresa debe ser seleccionada.")
        try:
            cursor.execute("UPDATE Patients SET name = ?, surname = ?, document_number = ?, phone = ?, email = ?, age = ?, company_id = ? WHERE id = ?", (name, surname, document_number, phone, email, age, company_id, patient_id))
            conn.commit()
            flash('Paciente actualizado exitosamente.', 'success')
        except sqlite3.IntegrityError as e:
            conn.rollback()
            error_message = "Error de integridad. Verifique sus datos."
            if "UNIQUE constraint failed: Patients.document_number" in str(e):
                error_message = "El número de documento ya existe para otro paciente."
            flash(f'Error: {error_message}', 'danger')
            companies_for_form = cursor.execute("SELECT id, name FROM Companies ORDER BY name").fetchall()
            current_form_data = dict(request.form)
            current_form_data['id'] = patient_id
            return render_template('patient_form.html', patient_data=current_form_data, companies=companies_for_form, form_action_url=url_for('edit_patient', patient_id=patient_id), error=error_message)
        finally:
            if conn: conn.close()
        return redirect(url_for('home'))

    patient_data = cursor.execute("SELECT * FROM Patients WHERE id = ?", (patient_id,)).fetchone()
    if patient_data is None:
        flash('Paciente no encontrado.', 'warning')
        if conn: conn.close()
        return redirect(url_for('home'))
    companies_data = cursor.execute("SELECT id, name FROM Companies ORDER BY name").fetchall()
    if conn: conn.close()
    return render_template('patient_form.html', patient=patient_data, companies=companies_data, form_action_url=url_for('edit_patient', patient_id=patient_id))

@app.route('/delete_patient/<int:patient_id>', methods=['POST'])
@login_required
def delete_patient(patient_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM MedicalRecords WHERE patient_id = ?", (patient_id,))
        cursor.execute("DELETE FROM Patients WHERE id = ?", (patient_id,))
        conn.commit()
        flash('Paciente y sus registros médicos asociados eliminados exitosamente.', 'success')
    except Exception as e:
        conn.rollback()
        print(f"Error al eliminar paciente: {e}")
        flash('Error al eliminar el paciente y sus registros asociados.', 'danger')
    finally:
        if conn: conn.close()
    return redirect(url_for('home'))

def get_patient_company_id(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT company_id FROM Patients WHERE id = ?", (patient_id,))
    result = cursor.fetchone()
    conn.close()
    return result['company_id'] if result else None

@app.route('/add_medical_record', methods=['GET', 'POST'])
@login_required
def add_medical_record():
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        patient_id_form = request.form.get('patient_id', type=int)
        diagnosis = request.form['diagnosis']
        date = request.form['date']
        if not patient_id_form:
            flash('Error: El paciente debe ser seleccionado.', 'danger')
            patients_for_form = cursor.execute("SELECT id, name, surname, document_number FROM Patients ORDER BY surname, name").fetchall()
            return render_template('medical_record_form.html', patients=patients_for_form, form_action_url=url_for('add_medical_record'), error="El paciente debe ser seleccionado.", record_data=request.form)
        company_id = get_patient_company_id(patient_id_form)
        if company_id is None:
            flash('Error: El paciente seleccionado no tiene una empresa asociada.', 'danger')
            patients_for_form = cursor.execute("SELECT id, name, surname, document_number FROM Patients ORDER BY surname, name").fetchall()
            return render_template('medical_record_form.html', patients=patients_for_form, form_action_url=url_for('add_medical_record'), error="El paciente seleccionado no tiene una empresa asociada.", record_data=request.form)
        try:
            cursor.execute("INSERT INTO MedicalRecords (patient_id, diagnosis, date, company_id) VALUES (?, ?, ?, ?)", (patient_id_form, diagnosis, date, company_id))
            conn.commit()
            flash('Registro médico agregado exitosamente.', 'success')
        except Exception as e:
            conn.rollback()
            print(f"Error al agregar registro médico: {e}")
            flash(f'Error al agregar el registro médico: {e}', 'danger')
            patients_for_form = cursor.execute("SELECT id, name, surname, document_number FROM Patients ORDER BY surname, name").fetchall()
            return render_template('medical_record_form.html', patients=patients_for_form, form_action_url=url_for('add_medical_record'), error=f"Ocurrió un error: {e}", record_data=request.form)
        finally:
            if conn: conn.close()

        patient_doc_num_cursor = get_db_connection()
        patient_doc_num_cursor.execute("SELECT document_number FROM Patients WHERE id = ?", (patient_id_form,))
        patient_doc_num_row = patient_doc_num_cursor.fetchone()
        patient_doc_num_cursor.connection.close()
        if patient_doc_num_row:
             return redirect(url_for('home', search_patient_document=patient_doc_num_row['document_number']))
        return redirect(url_for('home'))

    patients_data = cursor.execute("SELECT id, name, surname, document_number FROM Patients ORDER BY surname, name").fetchall()
    if conn: conn.close()
    return render_template('medical_record_form.html', patients=patients_data, form_action_url=url_for('add_medical_record'))

@app.route('/add_medical_record/<int:patient_id>', methods=['GET', 'POST'])
@login_required
def add_medical_record_for_patient(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT p.*, c.name as company_name FROM Patients p LEFT JOIN Companies c ON p.company_id = c.id WHERE p.id = ?", (patient_id,))
    patient = cursor.fetchone()
    if not patient:
        flash("Paciente no encontrado.", 'warning')
        if conn: conn.close()
        return redirect(url_for('home'))
    if request.method == 'POST':
        diagnosis = request.form['diagnosis']
        date = request.form['date']
        company_id = patient['company_id']
        if not company_id:
            flash("Error: La información de la empresa del paciente está incompleta. No se puede agregar el registro.", 'danger')
            return render_template('medical_record_form.html', patient=patient, company_name=patient['company_name'], form_action_url=url_for('add_medical_record_for_patient', patient_id=patient_id), error="La información de la empresa del paciente está incompleta.")
        try:
            cursor.execute("INSERT INTO MedicalRecords (patient_id, diagnosis, date, company_id) VALUES (?, ?, ?, ?)", (patient_id, diagnosis, date, company_id))
            conn.commit()
            flash('Registro médico agregado exitosamente para el paciente.', 'success')
        except Exception as e:
            conn.rollback()
            print(f"Error al agregar registro médico para paciente {patient_id}: {e}")
            flash(f'Error al agregar el registro médico: {e}', 'danger')
            return render_template('medical_record_form.html', patient=patient, company_name=patient['company_name'], form_action_url=url_for('add_medical_record_for_patient', patient_id=patient_id), error=f"Ocurrió un error: {e}", record_data=request.form)
        finally:
            if conn: conn.close()
        return redirect(url_for('home', search_patient_document=patient['document_number']))

    if conn: conn.close()
    return render_template('medical_record_form.html', patient=patient, company_name=patient['company_name'], form_action_url=url_for('add_medical_record_for_patient', patient_id=patient_id))

@app.route('/edit_medical_record/<int:record_id>', methods=['GET', 'POST'])
@login_required
def edit_medical_record(record_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        diagnosis = request.form['diagnosis']
        date = request.form['date']
        cursor.execute("SELECT patient_id FROM MedicalRecords WHERE id = ?", (record_id,))
        record_for_redirect = cursor.fetchone()
        try:
            cursor.execute("UPDATE MedicalRecords SET diagnosis = ?, date = ? WHERE id = ?", (diagnosis, date, record_id))
            conn.commit()
            flash('Registro médico actualizado exitosamente.', 'success')
        except Exception as e:
            conn.rollback()
            print(f"Error al actualizar registro médico: {e}")
            flash(f'Error al actualizar el registro médico: {e}', 'danger')
            cursor.execute("SELECT mr.*, p.name as p_name, p.surname as p_surname, p.document_number as p_doc, c.name as c_name FROM MedicalRecords mr JOIN Patients p ON mr.patient_id = p.id JOIN Companies c ON mr.company_id = c.id WHERE mr.id = ?", (record_id,))
            record_data_for_form = cursor.fetchone()
            if not record_data_for_form:
                flash("Registro médico no encontrado.", 'warning')
                if conn: conn.close()
                return redirect(url_for('home'))
            patient_details = {'name': record_data_for_form['p_name'], 'surname': record_data_for_form['p_surname'], 'document_number': record_data_for_form['p_doc']}
            company_details = {'name': record_data_for_form['c_name']}
            return render_template('medical_record_form.html', record=record_data_for_form, patient_details=patient_details, company_details=company_details, form_action_url=url_for('edit_medical_record', record_id=record_id), error=f"Ocurrió un error: {e}")
        finally:
            if conn: conn.close()

        if record_for_redirect:
            patient_conn_redirect = get_db_connection() # New connection for this specific query
            patient_cursor_redirect = patient_conn_redirect.cursor()
            patient_cursor_redirect.execute("SELECT document_number FROM Patients WHERE id = ?", (record_for_redirect['patient_id'],))
            patient_info_redirect = patient_cursor_redirect.fetchone()
            patient_conn_redirect.close()
            if patient_info_redirect:
                return redirect(url_for('home', search_patient_document=patient_info_redirect['document_number']))
        return redirect(url_for('home'))

    cursor.execute("SELECT mr.*, p.name as patient_name, p.surname as patient_surname, p.document_number as patient_document_number, c.name as company_name FROM MedicalRecords mr JOIN Patients p ON mr.patient_id = p.id LEFT JOIN Companies c ON mr.company_id = c.id WHERE mr.id = ?", (record_id,))
    record = cursor.fetchone()
    if record is None:
        flash("Registro médico no encontrado.", 'warning')
        if conn: conn.close()
        return redirect(url_for('home'))
    patient_details = {'name': record['patient_name'], 'surname': record['patient_surname'], 'document_number': record['patient_document_number']}
    company_details = {'name': record['company_name']}
    if conn: conn.close()
    return render_template('medical_record_form.html', record=record, patient_details=patient_details, company_details=company_details, form_action_url=url_for('edit_medical_record', record_id=record_id))

@app.route('/delete_medical_record/<int:record_id>', methods=['POST'])
@login_required
def delete_medical_record(record_id):
    conn = get_db_connection()
    patient_doc_for_redirect = None
    try:
        cursor = conn.cursor()
        # Fetch patient_id for redirect before deleting
        cursor.execute("SELECT p.document_number FROM MedicalRecords mr JOIN Patients p ON mr.patient_id = p.id WHERE mr.id = ?", (record_id,))
        patient_info_for_redirect = cursor.fetchone()
        if patient_info_for_redirect:
            patient_doc_for_redirect = patient_info_for_redirect['document_number']

        cursor.execute("DELETE FROM MedicalRecords WHERE id = ?", (record_id,))
        conn.commit()
        flash('Registro médico eliminado exitosamente.', 'success')
    except Exception as e:
        conn.rollback()
        print(f"Error al eliminar registro médico: {e}")
        flash('Error al eliminar el registro médico.', 'danger')
    finally:
        if conn: conn.close()

    if patient_doc_for_redirect:
        return redirect(url_for('home', search_patient_document=patient_doc_for_redirect))
    return redirect(url_for('home'))

def generate_medical_record_pdf(record_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT mr.id, mr.diagnosis, mr.date, p.name as patient_name, p.surname as patient_surname, p.document_number, c.name as company_name, c.email as company_email FROM MedicalRecords mr JOIN Patients p ON mr.patient_id = p.id JOIN Companies c ON mr.company_id = c.id WHERE mr.id = ?"
    cursor.execute(query, (record_id,))
    data = cursor.fetchone()
    conn.close()
    if not data:
        print(f"No se encontraron datos para el registro PDF ID: {record_id}")
        return None
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Dirigido a: {data['company_name']}", ln=1, align="L")
    pdf.ln(5)
    pdf.cell(200, 10, txt=f"Paciente: {data['patient_name']} {data['patient_surname']}", ln=1, align="L")
    pdf.cell(200, 10, txt=f"Documento: {data['document_number']}", ln=1, align="L")
    pdf.cell(200, 10, txt=f"Fecha de Atención: {data['date']}", ln=1, align="L")
    pdf.ln(5)
    pdf.set_font("Arial", 'B', size=12)
    pdf.cell(200, 10, txt="Diagnóstico:", ln=1, align="L")
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 10, txt=data['diagnosis'], border=0, align="L")
    pdf.ln(10)
    pdf.cell(200, 10, txt="Firmado: Dr. Juan Pablo Moya", ln=1, align="L")
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
        flash("No se pudo generar el PDF: Registro médico no encontrado.", 'warning')
        return redirect(url_for('home'))

def send_medical_record_email(record_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT mr.id as record_id, mr.date as record_date, p.name as patient_name, p.surname as patient_surname, p.document_number, c.name as company_name, c.email as company_email FROM MedicalRecords mr JOIN Patients p ON mr.patient_id = p.id JOIN Companies c ON mr.company_id = c.id WHERE mr.id = ?"
    cursor.execute(query, (record_id,))
    data = cursor.fetchone()
    conn.close()
    if not data or not data['company_email']:
        print(f"Correo no enviado: Datos no encontrados o correo de empresa faltante para registro {record_id}.")
        return False
    pdf_content = generate_medical_record_pdf(record_id)
    if not pdf_content:
        print(f"Correo no enviado: Falló la generación de PDF para registro {record_id}.")
        return False
    msg = MIMEMultipart()
    msg['Subject'] = f"Informe Médico del Paciente: {data['patient_name']} {data['patient_surname']} ({data['record_date']})"
    msg['From'] = EMAIL_SENDER
    msg['To'] = data['company_email']
    body = f"Estimada {data['company_name']},\n\nAdjunto encontrará el informe médico del paciente {data['patient_name']} {data['patient_surname']}, atendido el {data['record_date']}.\n\nSaludos cordiales,\nDr. Juan Pablo Moya"
    msg.attach(MIMEText(body, 'plain'))
    pdf_attachment = MIMEApplication(pdf_content, _subtype="pdf")
    pdf_attachment.add_header('Content-Disposition', 'attachment', filename=f'informe_medico_{data["document_number"]}_{data["record_date"]}.pdf')
    msg.attach(pdf_attachment)
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(EMAIL_SENDER, data['company_email'], msg.as_string())
        print(f"Correo para registro {record_id} enviado exitosamente a {data['company_email']}.")
        return True
    except smtplib.SMTPException as e:
        print(f"SMTPException al enviar correo para registro {record_id}: {e}")
    except ConnectionRefusedError as e:
        print(f"ConnectionRefusedError al enviar correo para registro {record_id}: {e} (Verifique servidor SMTP y puerto)")
    except socket.gaierror as e:
        print(f"Socket gaierror al enviar correo para registro {record_id}: {e} (Verifique nombre de servidor SMTP)")
    except Exception as e:
        print(f"Error inesperado al enviar correo para registro {record_id}: {e}")
    return False

@app.route('/medical_record/<int:record_id>/send_email', methods=['POST'])
@login_required
def email_medical_record(record_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT p.document_number, c.email as company_email, c.name as company_name FROM MedicalRecords mr JOIN Patients p ON mr.patient_id = p.id JOIN Companies c ON mr.company_id = c.id WHERE mr.id = ?", (record_id,))
    info = cursor.fetchone()
    conn.close()

    patient_document_number = info['document_number'] if info else None
    company_email_display = info['company_email'] if info and info['company_email'] else None
    company_name_display = info['company_name'] if info and info['company_name'] else "la empresa (nombre no encontrado)"

    if not company_email_display:
        flash(f"No se pudo enviar el correo: Email de la empresa '{company_name_display}' no encontrado para el registro {record_id}.", "danger")
        return redirect(url_for('home', search_patient_document=patient_document_number if patient_document_number else ''))
    if SMTP_SERVER == 'smtp.example.com' or SMTP_USERNAME == 'your_email@example.com' or SMTP_PASSWORD == 'your_app_password':
        flash("La configuración de correo electrónico (SMTP) no ha sido actualizada desde los valores predeterminados. Por favor, configure el servidor de correo para enviar emails.", "warning")
        return redirect(url_for('home', search_patient_document=patient_document_number if patient_document_number else ''))
    success = send_medical_record_email(record_id)
    if success:
        flash(f"Correo enviado exitosamente a {company_email_display} ({company_name_display}).", "success")
    else:
        flash(f"Error al enviar el correo a {company_email_display} ({company_name_display}). Verifique la configuración y el log del servidor.", "danger")
    return redirect(url_for('home', search_patient_document=patient_document_number if patient_document_number else ''))

if __name__ == "__main__":
    init_db()
    add_default_user()
    print("Aplicación Gestor Clínica definida. Para ejecutar, use 'flask run' después de configurar FLASK_APP.")
