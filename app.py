import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import smtplib
from email.mime.text import MIMEText

# --- CONFIGURACIÓN DE LA APLICACIÓN Y BASE DE DATOS ---
app = Flask(__name__)

# Configuración de la base de datos SQLite (se crea un archivo 'shifts.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///shifts.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'una_clave_secreta_fuerte') # Clave de sesión
db = SQLAlchemy(app)

# Tasa de pago y configuración de administración
PAY_RATE_PER_HOUR = 9.00  # 9€ por hora
DEFAULT_CAR_ALLOWANCE = 5.00 # Subsidio de coche predeterminado (por ejemplo, 5€)

# Configuración de Email para Notificaciones (¡IMPORTANTE!)
# Debes configurar la contraseña de aplicación o permitir acceso de apps menos seguras en Gmail.
EMAIL_ADDRESS = 'fdepaulajodaracuna@gmail.com' # <-- ¡TU EMAIL CONFIGURADO!
EMAIL_PASSWORD = '97139586pacoO!' # <--- ¡ACTUALIZADO CON TU CONTRASEÑA!
MANAGER_EMAIL = 'fdepaulajodaracuna@gmail.com' # Email del administrador para recibir notificaciones
SMTP_SERVER = 'smtp.gmail.com' # Para Gmail
SMTP_PORT = 587 # Puerto TLS

# --- MODELOS DE BASE DE DATOS ---
class User(db.Model):
    """Modelo para Camareros y Administrador"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    # Relación con Shifts
    shifts = db.relationship('Shift', backref='waiter', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Shift(db.Model):
    """Modelo para registrar las horas trabajadas"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time_in = db.Column(db.Time, nullable=False)
    time_out = db.Column(db.Time, nullable=False)
    car_used = db.Column(db.Boolean, default=False)
    car_allowance = db.Column(db.Float, default=DEFAULT_CAR_ALLOWANCE) # Subsidio extra por coche para ese día

    def calculate_hours(self):
        """Calcula el total de horas trabajadas como un timedelta"""
        dt_in = datetime.combine(self.date, self.time_in)
        dt_out = datetime.combine(self.date, self.time_out)

        # Maneja el caso de turno nocturno (salida al día siguiente)
        if dt_out < dt_in:
            dt_out += timedelta(days=1)

        return dt_out - dt_in

    def calculate_pay(self):
        """Calcula el pago total para este turno (incluye subsidio de coche)"""
        time_worked = self.calculate_hours()
        hours = time_worked.total_seconds() / 3600 # Convertir a horas
        pay = hours * PAY_RATE_PER_HOUR
        if self.car_used:
            pay += self.car_allowance
        return pay

# --- FUNCIONES DE UTILIDAD ---

def send_shift_notification(waiter_name, date_str, time_in_str, time_out_str):
    """Envía un email al administrador con la notificación del nuevo turno."""
    try:
        msg = MIMEText(
            f"El camarero {waiter_name} ha registrado un nuevo turno.\n"
            f"Fecha: {date_str}\n"
            f"Entrada: {time_in_str}\n"
            f"Salida: {time_out_str}\n"
            f"Coche Usado: {'Sí' if Shift.query.order_by(Shift.id.desc()).first().car_used else 'No'}"
        )
        msg['Subject'] = f'NUEVO TURNO REGISTRADO: {waiter_name}'
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = MANAGER_EMAIL

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()  # Usa TLS
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, MANAGER_EMAIL, msg.as_string())
        print("Notificación por email enviada con éxito.")
    except Exception as e:
        print(f"Error al enviar la notificación por email. Verifica EMAIL_ADDRESS y EMAIL_PASSWORD: {e}")
        # En una aplicación real, se usaría un sistema de logs más robusto

def login_required(f):
    """Decorador para restringir acceso a usuarios no logueados"""
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, inicia sesión para acceder a esta página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def admin_required(f):
    """Decorador para restringir acceso solo al administrador"""
    @login_required
    def decorated_function(*args, **kwargs):
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            flash('Acceso denegado. Solo para administradores.', 'danger')
            return redirect(url_for('waiter_dashboard'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# --- RUTAS DE LA APLICACIÓN ---

@app.before_first_request
def create_db_and_admin():
    """Crea la base de datos y un usuario administrador inicial si no existen."""
    db.create_all()

    # Crea un usuario administrador por defecto (¡CAMBIA ESTAS CREDENCIALES!)
    if not User.query.filter_by(is_admin=True).first():
        admin = User(username='admin', is_admin=True)
        admin.set_password('jefe_secreto123')
        db.session.add(admin)
        db.session.commit()
        print("¡ADMIN CREADO! Usuario: admin, Contraseña: jefe_secreto123. ¡CÁMBIALA INMEDIATAMENTE!")


@app.route('/')
def index():
    """Redirige al dashboard o al login si no ha iniciado sesión."""
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user.is_admin:
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('waiter_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Ruta para el registro inicial de camareros."""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('Ambos campos son obligatorios.', 'danger')
            return render_template('register.html')

        if User.query.filter_by(username=username).first():
            flash('El nombre de usuario ya existe.', 'danger')
            return render_template('register.html')

        new_user = User(username=username, is_admin=False)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash('Registro exitoso. ¡Ahora puedes iniciar sesión!', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Ruta para el inicio de sesión."""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            flash(f'¡Bienvenido, {user.username}!', 'success')
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('waiter_dashboard'))
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    """Cierra la sesión del usuario."""
    session.pop('user_id', None)
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('login'))


@app.route('/waiter/dashboard', methods=['GET', 'POST'])
@login_required
def waiter_dashboard():
    """Dashboard del camarero para registrar turnos."""
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        try:
            date_str = request.form.get('date')
            time_in_str = request.form.get('time_in')
            time_out_str = request.form.get('time_out')
            car_used = request.form.get('car_used') == 'yes'

            # Convertir strings a objetos date y time
            shift_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            time_in = datetime.strptime(time_in_str, '%H:%M').time()
            time_out = datetime.strptime(time_out_str, '%H:%M').time()

            new_shift = Shift(
                user_id=user.id,
                date=shift_date,
                time_in=time_in,
                time_out=time_out,
                car_used=car_used,
                car_allowance=DEFAULT_CAR_ALLOWANCE # Se puede modificar más tarde por el admin
            )
            
            db.session.add(new_shift)
            db.session.commit()
            
            # Enviar notificación por email
            send_shift_notification(user.username, date_str, time_in_str, time_out_str)
            
            flash('Turno registrado con éxito. ¡Se ha enviado la notificación al jefe!', 'success')

        except Exception as e:
            flash(f'Error al registrar el turno. Asegúrate de que los formatos sean correctos. Error: {e}', 'danger')

        return redirect(url_for('waiter_dashboard'))

    return render_template('waiter_dashboard.html', username=user.username, today=datetime.now().strftime('%Y-%m-%d'))


@app.route('/admin/dashboard', methods=['GET', 'POST'])
@admin_required
def admin_dashboard():
    """Dashboard del administrador para ver horas, nóminas y ajustes."""
    
    # Lógica para mostrar las nóminas
    waiters = User.query.filter_by(is_admin=False).all()
    payroll_data = []

    for waiter in waiters:
        waiter_data = {
            'username': waiter.username,
            'user_id': waiter.id,
            'years': {} # {2023: {1: {total_hours: X, total_pay: Y, shifts: [...]}}}
        }
        
        # Obtener todos los turnos del camarero y ordenarlos por fecha descendente
        all_shifts = Shift.query.filter_by(user_id=waiter.id).order_by(Shift.date.desc()).all()
        
        for shift in all_shifts:
            year = shift.date.year
            month = shift.date.month

            if year not in waiter_data['years']:
                waiter_data['years'][year] = {}
            if month not in waiter_data['years'][year]:
                waiter_data['years'][year][month] = {
                    'total_hours_sec': 0,
                    'total_pay': 0.0,
                    'shifts': [],
                    'total_car_pay': 0.0
                }
            
            # Calcular datos del turno
            hours_worked = shift.calculate_hours().total_seconds()
            pay_earned = shift.calculate_pay()
            
            # Acumular datos mensuales
            waiter_data['years'][year][month]['total_hours_sec'] += hours_worked
            waiter_data['years'][year][month]['total_pay'] += pay_earned
            if shift.car_used:
                 waiter_data['years'][year][month]['total_car_pay'] += shift.car_allowance
            
            # Detalle del turno
            shift_detail = {
                'date': shift.date.strftime('%d-%m-%Y'),
                'time_in': shift.time_in.strftime('%H:%M'),
                'time_out': shift.time_out.strftime('%H:%M'),
                'hours_decimal': round(hours_worked / 3600, 2),
                'hourly_pay': round(hours_worked / 3600 * PAY_RATE_PER_HOUR, 2),
                'car_used': shift.car_used,
                'car_allowance': shift.car_allowance if shift.car_used else 0.0,
                'total_day_pay': round(pay_earned, 2),
                'id': shift.id
            }
            waiter_data['years'][year][month]['shifts'].append(shift_detail)
            
        # Formatear las horas totales a HH:MM y total de pago a 2 decimales
        for year, months in waiter_data['years'].items():
            for month, data in months.items():
                total_hours_delta = timedelta(seconds=data['total_hours_sec'])
                
                # Convertir segundos a formato HH:MM (simple)
                hours, remainder = divmod(total_hours_delta.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                data['total_hours_str'] = f"{int(total_hours_delta.days * 24 + hours):02d}h {minutes:02d}m"
                data['total_pay'] = round(data['total_pay'], 2)
                data['total_car_pay'] = round(data['total_car_pay'], 2)


        payroll_data.append(waiter_data)

    return render_template('admin_dashboard.html', 
                           payroll_data=payroll_data, 
                           pay_rate=PAY_RATE_PER_HOUR, 
                           default_allowance=DEFAULT_CAR_ALLOWANCE)

@app.route('/admin/update_allowance/<int:shift_id>', methods=['POST'])
@admin_required
def update_allowance(shift_id):
    """Permite al administrador actualizar el subsidio de coche para un turno específico."""
    shift = Shift.query.get_or_404(shift_id)
    
    # Asegurarse de que solo se pueda modificar si el coche fue usado
    if not shift.car_used:
        flash('No se puede actualizar el subsidio, el coche no fue usado para este turno.', 'danger')
        return redirect(url_for('admin_dashboard'))

    try:
        new_allowance = float(request.form.get('new_allowance'))
        if new_allowance < 0:
            raise ValueError("El subsidio no puede ser negativo.")

        shift.car_allowance = new_allowance
        db.session.commit()
        flash(f'Subsidio de coche actualizado a {new_allowance}€ para el turno del {shift.date}.', 'success')
    except ValueError:
        flash('Valor de subsidio inválido.', 'danger')
    except Exception as e:
        flash(f'Error al actualizar el subsidio: {e}', 'danger')

    return redirect(url_for('admin_dashboard'))


# --- INICIO DE LA APLICACIÓN ---
if __name__ == '__main__':
    with app.app_context():
        # Inicializa la base de datos y crea el admin
        create_db_and_admin()
    app.run(debug=True) # debug=True es solo para desarrollo