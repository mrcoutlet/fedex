import os
import sys
from datetime import datetime, timezone, timedelta
from io import BytesIO
from functools import wraps
from collections import defaultdict
import pytz

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message

# Ensure python-dotenv is installed: pip install python-dotenv
from dotenv import load_dotenv

# Import TypeDecorator for custom SQLAlchemy type handling
from sqlalchemy.types import TypeDecorator, DateTime

# --- 1. Environment Variable Loading (Crucial for .env with PyInstaller) ---
# Determine the base directory for loading resources, especially for PyInstaller
if getattr(sys, 'frozen', False):
    # If running in a PyInstaller bundle, sys._MEIPASS is the temporary extraction directory
    bundle_dir = sys._MEIPASS
else:
    # If running in a normal Python environment, use the script's directory
    bundle_dir = os.path.abspath(os.path.dirname(__file__))

# Construct the full path to the .env file
dotenv_path = os.path.join(bundle_dir, '.env')

# Load environment variables from the .env file
# This must happen before Flask app initialization if config relies on them
load_dotenv(dotenv_path=dotenv_path)

# --- IMPORTANT: WeasyPrint Dependency Check ---
HTML = None
try:
    # Ensure WeasyPrint is installed: pip install WeasyPrint
    # And its system dependencies are met (see warning below)
    from weasyprint import HTML
except ImportError:
    HTML = None
    print("\n--------------------------------------------------------------")
    print("WARNING: WeasyPrint not installed or its system dependencies missing.")
    print("PDF generation will be disabled. To enable, install WeasyPrint and its dependencies:")
    print("For Linux (Debian/Ubuntu): sudo apt-get install python3-dev libffi-dev libssl-dev libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev libpango1.0-dev libcairo2-dev")
    print("For macOS (Homebrew): brew install cairo pango gdk-pixbuf libffi")
    print("For Windows: Refer to WeasyPrint docs (https://weasyprint.org/docs/latest/install.html) for complex setup, or omit PDF feature.")
    print("--------------------------------------------------------------\n")

if HTML:
    print("\n--------------------------------------------------------------")
    print("WeasyPrint (PDF generation) is ENABLED. Ensure system dependencies are met.")
    print("--------------------------------------------------------------\n")
else:
    print("\n------------------------------------------------------------------------------------")
    print("WARNING: WeasyPrint (PDF generation) is DISABLED. PDF download will not function.")
    print("To enable, uncomment 'from weasyprint import HTML' and remove 'HTML = None',")
    print("then install system dependencies as per WeasyPrint documentation.")
    print("------------------------------------------------------------------------------------\n")


app = Flask(__name__)

# --- 2. Flask App Configuration ---
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'a_default_secret_key_if_not_set')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Flask-Mail Configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() in ('true', '1', 't')
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'False').lower() in ('true', '1', 't')
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')
app.config['MAIL_DEBUG'] = app.debug # Set to True in development for verbose mail logs

# Ensure that only one of TLS or SSL is true, not both
if app.config['MAIL_USE_TLS'] and app.config['MAIL_USE_SSL']:
    print("Warning: Both MAIL_USE_TLS and MAIL_USE_SSL are True. Defaulting to TLS.")
    app.config['MAIL_USE_SSL'] = False

# Company Information (can be stored in DB or .env if needed)
COMPANY_NAME = os.getenv('COMPANY_NAME', 'MAIL+PC')
COMPANY_ADDRESS = os.getenv('COMPANY_ADDRESS', '310 E Orangethorpe Ave Ste M Placentia CA 92870')

# Define the timezone for display purposes (e.g., Pacific Time)
DISPLAY_TIMEZONE = pytz.timezone('America/Los_Angeles')


# --- 3. Initialize Extensions ---
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'
mail = Mail(app)


# --- 4. Custom SQLAlchemy Type for UTC Datetimes ---
class UTCDateTime(TypeDecorator):
    """
    A DateTime type that forces UTC and timezone awareness.
    Stores datetimes as UTC in the database and loads them as timezone-aware datetimes
    converted to DISPLAY_TIMEZONE.
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                # Assume naive datetimes are UTC if no tzinfo
                return value.replace(tzinfo=timezone.utc)
            else:
                # Convert to UTC if already timezone-aware
                return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                # Assume naive datetimes from DB are UTC
                value = value.replace(tzinfo=timezone.utc)
            # Convert to display timezone on retrieval
            return value.astimezone(DISPLAY_TIMEZONE)
        return value

# --- 5. Database Models ---
class User(db.Model, UserMixin):
    """User model for authentication."""
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False) # Added email for receipts
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))
    trackings = db.relationship('Tracking', backref='user', lazy=True)

    def set_password(self, password):
        """Hashes the password and stores it."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Checks a provided password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.phone_number}>'

class Tracking(db.Model):
    """
    Model to store FedEx tracking numbers.
    Stores only the last 12 digits as requested.
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # This field will now store the *last 12 digits* directly
    tracking_number = db.Column(db.String(12), nullable=False)
    timestamp = db.Column(UTCDateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Tracking {self.tracking_number}>"

# --- 6. Flask-Login user loader ---
@login_manager.user_loader
def load_user(user_id):
    """Loads a user from the database given their ID."""
    return User.query.get(int(user_id))

# --- 7. Helper Functions ---
def send_email(to_email, subject, html_body):
    """Helper function to send email."""
    msg = Message(subject, recipients=[to_email])
    msg.html = html_body
    try:
        with app.app_context(): # Ensure app context is active for mail.send()
            mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        raise # Re-raise the exception to be caught by the route's try-except

# --- 8. Routes ---

@app.route('/')
def index():
    """Home page - redirects to dashboard if logged in."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration route."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        phone_number = request.form.get('phone_number')
        email = request.form.get('email') # Get email from form
        password = request.form.get('password')

        if not phone_number or not email or not password:
            flash('Phone number, email, and password are required.', 'danger')
            return render_template('register.html')

        if User.query.filter_by(phone_number=phone_number).first():
            flash('Phone number already registered. Please log in.', 'warning')
            return redirect(url_for('login'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please use a different email.', 'warning')
            return render_template('register.html')

        new_user = User(phone_number=phone_number, email=email) # Pass email to User constructor
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login route."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        phone_number = request.form.get('phone_number')
        password = request.form.get('password')

        user = User.query.filter_by(phone_number=phone_number).first()
        if user and user.check_password(password):
            login_user(user)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid phone number or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """User logout route."""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    """User dashboard showing scanned packages, grouped by date."""
    all_user_trackings = Tracking.query.filter_by(user_id=current_user.id).order_by(Tracking.timestamp.desc()).all()

    # Group trackings by date in the DISPLAY_TIMEZONE
    trackings_by_display_date = defaultdict(list)
    for tracking in all_user_trackings:
        # The UTCDateTime custom type already converts to DISPLAY_TIMEZONE on retrieval
        display_timestamp = tracking.timestamp
        drop_off_date = display_timestamp.date()
        trackings_by_display_date[drop_off_date].append(tracking)

    # Sort groups by date, newest first
    grouped_trackings = sorted(trackings_by_display_date.items(), key=lambda item: item[0], reverse=True)

    dashboard_data = []
    for date_obj, trackings_list in grouped_trackings:
        # Use the ID of the first tracking in the list as a reference for the day's receipt/PDF
        reference_tracking_id = trackings_list[0].id if trackings_list else None

        # Sort trackings within each day by timestamp, oldest first
        trackings_list_sorted = sorted(trackings_list, key=lambda t: t.timestamp)

        trackings_for_template = []
        for track in trackings_list_sorted:
            display_timestamp_item = track.timestamp # Already in DISPLAY_TIMEZONE from UTCDateTime
            trackings_for_template.append({
                'id': track.id,
                'tracking_number': track.tracking_number, # This will be the 12-digit version
                'timestamp': display_timestamp_item.strftime('%I:%M %p %Z'),
                'full_timestamp': display_timestamp_item.strftime('%Y-%m-%d %I:%M %p %Z')
            })

        dashboard_data.append({
            'date': date_obj.strftime('%Y-%m-%d'),
            'package_count': len(trackings_list),
            'trackings': trackings_for_template,
            'reference_id': reference_tracking_id
        })

    total_package_count = len(all_user_trackings)

    return render_template('dashboard.html', grouped_trackings=dashboard_data, total_package_count=total_package_count)

@app.route('/add-tracking', methods=['POST'])
@login_required
def add_tracking():
    """
    Handles adding a new tracking number.
    Cleans the input and saves only the last 12 digits.
    """
    tracking_number_input = request.form.get('tracking_number')
    if not tracking_number_input:
        flash('Tracking number is required.', 'danger')
        return redirect(url_for('dashboard'))

    # Remove any non-digit characters from the input
    cleaned_number = ''.join(filter(str.isdigit, tracking_number_input))

    # Extract the last 12 digits for storage as requested
    final_tracking_number_to_save = cleaned_number
    if len(cleaned_number) > 12:
        final_tracking_number_to_save = cleaned_number[-12:]
    elif len(cleaned_number) < 12:
        # Optional: Add a more specific warning if the number is too short
        flash('Warning: Tracking number is less than 12 digits. Saving as provided.', 'warning')


    # Check for existing tracking number (using the 12-digit or cleaned version)
    existing_tracking = Tracking.query.filter_by(user_id=current_user.id, tracking_number=final_tracking_number_to_save).first()
    if existing_tracking:
        flash(f'Tracking number {final_tracking_number_to_save} already exists for your account.', 'warning')
        return redirect(url_for('dashboard'))

    new_tracking = Tracking(user_id=current_user.id, tracking_number=final_tracking_number_to_save)
    try:
        db.session.add(new_tracking)
        db.session.commit()
        flash(f'Package with tracking number {final_tracking_number_to_save} added successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        # Log the full error for debugging
        app.logger.error(f"Database error adding tracking number: {e}", exc_info=True)
        flash(f'Failed to add tracking number due to a database error. Please try again. ({e})', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/delete-tracking/<int:tracking_id>', methods=['POST'])
@login_required
def delete_tracking(tracking_id):
    """Deletes a tracking record."""
    tracking_to_delete = Tracking.query.filter_by(id=tracking_id, user_id=current_user.id).first()
    if tracking_to_delete:
        db.session.delete(tracking_to_delete)
        db.session.commit()
        flash('Tracking record deleted successfully.', 'success')
    else:
        flash('Tracking record not found or you do not have permission to delete it.', 'danger')
    return redirect(url_for('dashboard'))


@app.route('/get-tracking-details/<int:tracking_id>', methods=['GET'])
@login_required
def get_tracking_details(tracking_id):
    """
    Fetches details for a daily receipt based on a tracking ID from that day.
    Returns HTML content for the receipt modal.
    """
    selected_tracking = Tracking.query.filter_by(id=tracking_id, user_id=current_user.id).first()
    if not selected_tracking:
        return jsonify({"success": False, "message": "Tracking record not found."}), 404

    # UTCDateTime already converts to DISPLAY_TIMEZONE on retrieval
    receipt_date_obj_display_tz = selected_tracking.timestamp.date()

    # Create datetime objects for the start and end of the day in DISPLAY_TIMEZONE
    start_of_day_display_tz = datetime.combine(receipt_date_obj_display_tz, datetime.min.time())
    end_of_day_display_tz = datetime.combine(receipt_date_obj_display_tz, datetime.max.time())

    # Localize these dates to the display timezone, then convert to UTC for database query
    start_of_day_utc = DISPLAY_TIMEZONE.localize(start_of_day_display_tz).astimezone(timezone.utc)
    # For the end date, ensure we include the entire day in the display timezone
    end_of_day_utc = DISPLAY_TIMEZONE.localize(end_of_day_display_tz).astimezone(timezone.utc) + timedelta(microseconds=999999) # Include whole day up to last microsecond


    same_day_trackings = Tracking.query.filter(
        Tracking.user_id == current_user.id,
        Tracking.timestamp >= start_of_day_utc,
        Tracking.timestamp <= end_of_day_utc # Use <= for end of day
    ).order_by(Tracking.timestamp.asc()).all()

    if not same_day_trackings:
        return jsonify({"success": False, "message": "No tracking records found for this date."}), 404

    receipt_context = {
        "receipt_date": receipt_date_obj_display_tz.strftime('%Y-%m-%d'),
        "company_name": COMPANY_NAME,
        "company_address": COMPANY_ADDRESS,
        "trackings_for_day": [],
        "total_packages": len(same_day_trackings)
    }

    for track in same_day_trackings:
        display_timestamp_item = track.timestamp # Already in DISPLAY_TIMEZONE from UTCDateTime
        receipt_context["trackings_for_day"].append({
            "tracking_number": track.tracking_number,
            "timestamp": display_timestamp_item.strftime('%I:%M %p %Z'),
            "full_timestamp": display_timestamp_item.strftime('%Y-%m-%d %I:%M %p %Z')
        })

    receipt_html = render_template('receipt.html', **receipt_context)
    return jsonify({"success": True, "receiptHtml": receipt_html, "receiptData": receipt_context})


@app.route('/email-receipt-dashboard/<int:tracking_id>', methods=['POST'])
@login_required
def email_receipt_dashboard(tracking_id):
    """
    Sends an email receipt for a specific package's drop-off day from the dashboard.
    The email contains all packages dropped off on that specific day.
    """
    selected_tracking = Tracking.query.filter_by(id=tracking_id, user_id=current_user.id).first()
    if not selected_tracking:
        flash('Tracking record not found or you do not have permission to access it.', 'danger')
        return redirect(url_for('dashboard'))

    # UTCDateTime already converts to DISPLAY_TIMEZONE on retrieval
    receipt_date_obj_display_tz = selected_tracking.timestamp.date()

    start_of_day_display_tz = datetime.combine(receipt_date_obj_display_tz, datetime.min.time())
    end_of_day_display_tz = datetime.combine(receipt_date_obj_display_tz, datetime.max.time())

    start_of_day_utc = DISPLAY_TIMEZONE.localize(start_of_day_display_tz).astimezone(timezone.utc)
    end_of_day_utc = DISPLAY_TIMEZONE.localize(end_of_day_display_tz).astimezone(timezone.utc) + timedelta(microseconds=999999)

    same_day_trackings = Tracking.query.filter(
        Tracking.user_id == current_user.id,
        Tracking.timestamp >= start_of_day_utc,
        Tracking.timestamp <= end_of_day_utc
    ).order_by(Tracking.timestamp.asc()).all()

    if not same_day_trackings:
        flash("No tracking records found for this date to email.", 'warning')
        return redirect(url_for('dashboard'))

    receipt_context = {
        "receipt_date": receipt_date_obj_display_tz.strftime('%Y-%m-%d'),
        "company_name": COMPANY_NAME,
        "company_address": COMPANY_ADDRESS,
        "trackings_for_day": [],
        "total_packages": len(same_day_trackings)
    }

    for track in same_day_trackings:
        display_timestamp_item = track.timestamp # Already in DISPLAY_TIMEZONE from UTCDateTime
        receipt_context["trackings_for_day"].append({
            "tracking_number": track.tracking_number,
            "timestamp": display_timestamp_item.strftime('%I:%M %p %Z'),
            "full_timestamp": display_timestamp_item.strftime('%Y-%m-%d %I:%M %p %Z')
        })

    email_body_html = render_template('receipt.html', **receipt_context)

    try:
        recipient_email = current_user.email # Send to the logged-in user's email
        if not recipient_email: # Fallback if email is somehow missing
            flash("Your account does not have an email address configured for sending receipts.", 'danger')
            return redirect(url_for('dashboard'))

        subject = f"Package Drop-off Receipt - {receipt_context['receipt_date']} ({receipt_context['total_packages']} items)"
        send_email(
            recipient_email,
            subject,
            email_body_html
        )
        flash("Receipt emailed successfully!", 'success')
    except Exception as e:
        app.logger.error(f"Error sending email: {e}", exc_info=True)
        flash(f"Failed to send email: {str(e)}", 'danger')

    return redirect(url_for('dashboard'))


@app.route('/download-pdf-dashboard/<int:tracking_id>', methods=['GET'])
@login_required
def download_pdf_dashboard(tracking_id):
    """
    Generates and downloads a PDF receipt for a specific package's drop-off day.
    The PDF contains all packages dropped off on that specific day.
    """
    selected_tracking = Tracking.query.filter_by(id=tracking_id, user_id=current_user.id).first()
    if not selected_tracking:
        flash('Tracking record not found or you do not have permission to access it.', 'danger')
        return redirect(url_for('dashboard'))

    # UTCDateTime already converts to DISPLAY_TIMEZONE on retrieval
    receipt_date_obj_display_tz = selected_tracking.timestamp.date()

    start_of_day_display_tz = datetime.combine(receipt_date_obj_display_tz, datetime.min.time())
    end_of_day_display_tz = datetime.combine(receipt_date_obj_display_tz, datetime.max.time())

    start_of_day_utc = DISPLAY_TIMEZONE.localize(start_of_day_display_tz).astimezone(timezone.utc)
    end_of_day_utc = DISPLAY_TIMEZONE.localize(end_of_day_display_tz).astimezone(timezone.utc) + timedelta(microseconds=999999)

    same_day_trackings = Tracking.query.filter(
        Tracking.user_id == current_user.id,
        Tracking.timestamp >= start_of_day_utc,
        Tracking.timestamp <= end_of_day_utc
    ).order_by(Tracking.timestamp.asc()).all()

    if not same_day_trackings:
        flash("No tracking records found for this date to generate PDF.", 'warning')
        return redirect(url_for('dashboard'))

    receipt_context = {
        "receipt_date": receipt_date_obj_display_tz.strftime('%Y-%m-%d'),
        "company_name": COMPANY_NAME,
        "company_address": COMPANY_ADDRESS,
        "trackings_for_day": [],
        "total_packages": len(same_day_trackings)
    }

    for track in same_day_trackings:
        display_timestamp_item = track.timestamp # Already in DISPLAY_TIMEZONE from UTCDateTime
        receipt_context["trackings_for_day"].append({
            "tracking_number": track.tracking_number,
            "timestamp": display_timestamp_item.strftime('%I:%M %p %Z'),
            "full_timestamp": display_timestamp_item.strftime('%Y-%m-%d %I:%M %p %Z')
        })

    if HTML: # Check if WeasyPrint was successfully imported
        rendered_html = render_template('receipt.html', **receipt_context)
        try:
            pdf_bytes = HTML(string=rendered_html).write_pdf()

            pdf_io = BytesIO(pdf_bytes)

            download_filename = f"receipt_{receipt_date_obj_display_tz.strftime('%Y%m%d')}_{receipt_context['total_packages']}_items.pdf"

            return send_file(
                pdf_io,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=download_filename # Corrected variable name
            )
        except Exception as e:
            app.logger.error(f"Error generating PDF: {e}", exc_info=True)
            flash(f"Failed to generate PDF: {str(e)}", 'danger')
            return redirect(url_for('dashboard')) # Redirect back to dashboard on error
    else:
        flash("PDF generation (WeasyPrint) is not available on this server. Please install it to use this feature.", 'danger')
        return redirect(url_for('dashboard')) # Redirect back to dashboard on error


@app.route('/search-dropoffs')
@login_required
def search_dropoffs_page():
    """Renders the page for searching drop-offs by date range."""
    return render_template('search_dropoffs.html')

@app.route('/api/get-dropoffs-in-range', methods=['POST'])
@login_required
def get_dropoffs_in_range():
    """API endpoint to get tracking records within a specified date range."""
    start_date_str = request.form.get('start_date')
    end_date_str = request.form.get('end_date')

    if not start_date_str or not end_date_str:
        return jsonify({"success": False, "message": "Start and end dates are required."}), 400

    try:
        # Interpret input dates as being in the DISPLAY_TIMEZONE
        start_date_display_tz = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
        end_date_display_tz = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)

        # Localize these dates to the display timezone, then convert to UTC for database query
        start_date_utc = DISPLAY_TIMEZONE.localize(start_date_display_tz).astimezone(timezone.utc)
        # For the end date, ensure we include the entire day in the display timezone
        end_date_utc = DISPLAY_TIMEZONE.localize(end_date_display_tz).astimezone(timezone.utc) + timedelta(microseconds=999999)


    except ValueError:
        return jsonify({"success": False, "message": "Invalid date format. Please use YYYY-MM-DD."}), 400

    trackings_in_range = Tracking.query.filter(
        Tracking.user_id == current_user.id,
        Tracking.timestamp >= start_date_utc,
        Tracking.timestamp <= end_date_utc # Use <= for end of day
    ).order_by(Tracking.timestamp.asc()).all()

    results = []
    for track in trackings_in_range:
        # Convert UTC timestamp to display timezone for the response (already done by UTCDateTime)
        display_timestamp = track.timestamp
        results.append({
            "tracking_number": track.tracking_number,
            "timestamp": display_timestamp.strftime('%Y-%m-%d %I:%M %p %Z')
        })

    return jsonify({
        "success": True,
        "trackings": results,
        "total_packages": len(results),
        "start_date": start_date_str,
        "end_date": end_date_str
    })

@app.route('/export-dropoffs-csv', methods=['GET'])
@login_required
def export_dropoffs_csv():
    """Exports tracking records within a specified date range to a CSV file."""
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    if not start_date_str or not end_date_str:
        flash('Start and end dates are required for CSV export.', 'danger')
        return redirect(url_for('search_dropoffs_page'))

    try:
        start_date_display_tz = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
        end_date_display_tz = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)

        start_date_utc = DISPLAY_TIMEZONE.localize(start_date_display_tz).astimezone(timezone.utc)
        end_date_utc = DISPLAY_TIMEZONE.localize(end_date_display_tz).astimezone(timezone.utc) + timedelta(microseconds=999999)

    except ValueError:
        flash('Invalid date format for CSV export. Please use YYYY-MM-DD.', 'danger')
        return redirect(url_for('search_dropoffs_page'))

    trackings_in_range = Tracking.query.filter(
        Tracking.user_id == current_user.id,
        Tracking.timestamp >= start_date_utc,
        Tracking.timestamp <= end_date_utc
    ).order_by(Tracking.timestamp.asc()).all()

    if not trackings_in_range:
        flash(f"No packages found for {start_date_str} to {end_date_str} to export.", 'info')
        return redirect(url_for('search_dropoffs_page'))

    import csv
    si = BytesIO() # Use BytesIO for binary CSV output
    # Use utf-8-sig for BOM, which helps Excel recognize UTF-8
    si.write(u'\ufeff'.encode('utf8')) # Add BOM for Excel compatibility
    cw = csv.writer(si)

    cw.writerow(['Tracking Number', 'Drop-off Date (Local Time)', 'Drop-off Time (Local Time)'])

    for track in trackings_in_range:
        display_timestamp = track.timestamp # Already in DISPLAY_TIMEZONE from UTCDateTime
        cw.writerow([
            track.tracking_number,
            display_timestamp.strftime('%Y-%m-%d'),
            display_timestamp.strftime('%I:%M:%S %p %Z')
        ])

    si.seek(0) # Rewind to the beginning of the BytesIO object

    filename = f"dropoffs_{start_date_str}_to_{end_date_str}.csv"

    return send_file(
        si,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


# --- 9. Error Handlers (Optional but good practice) ---
@app.errorhandler(404)
def page_not_found(e):
    """Custom 404 error page."""
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    """Custom 500 error page."""
    # Log the error for debugging
    app.logger.error(f"Internal Server Error: {e}", exc_info=True)
    return render_template('500.html'), 500

# --- 10. Database Creation and Application Run ---
if __name__ == '__main__':
    # This block ensures tables are created when you run 'python app.py' directly.
    # It's suitable for development.
    with app.app_context():
        db.create_all()
        print("Database tables created/checked.")
        # Optional: Create a default user if no users exist for easy testing
        # This is commented out by default to avoid creating users on every run
        # if not User.query.first():
        #     print("No users found. Creating a default user: phone=1234567890, email=test@example.com, password=password")
        #     default_user = User(phone_number='1234567890', email='test@example.com')
        #     default_user.set_password('password')
        #     db.session.add(default_user)
        #     db.session.commit()
        #     print("Default user created.")

    # Run the Flask application
    app.run(debug=os.getenv('FLASK_DEBUG', 'True').lower() in ('true', '1', 't'))
