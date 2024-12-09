import os
from flask import Flask, request, render_template, jsonify, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
import pdfplumber
import openai
from flask import send_file
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()


# Initialize Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.secret_key = 'supersecretkey'  # Secret key for session management

# Configure SQLAlchemy database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Set OpenAI API Key (replace with your key)
openai.api_key = os.getenv('OPENAI_API_KEY')

# Define User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(150), nullable=False)

# Create the database
with app.app_context():
    db.create_all()

# Route: Login Page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Authenticate user from the database
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['user'] = username  # Set user in session
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.')
    
    return render_template('login.html')

# Route: Signup Page
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Check if the username already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists.')
        else:
            # Add new user to the database
            new_user = User(username=username, password=password)
            db.session.add(new_user)
            db.session.commit()
            flash('Account created successfully! Please log in.')
            return redirect(url_for('login'))
    
    return render_template('signup.html')

# Route: Logout
@app.route('/logout')
def logout():
    session.pop('user', None)  # Clear session
    return redirect(url_for('login'))

# Route: Homepage
@app.route('/')
def index():
    if 'user' not in session:  # Check if user is logged in
        return redirect(url_for('login'))
    return render_template('index.html')


@app.route('/FreeSpeechSum')
def FreeSpeechSum():
    return render_template('FreeSpeechSum.html')

# Route: File Upload and Summarization
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'user' not in session:  # Check if user is logged in
        return redirect(url_for('login'))

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    # Save the uploaded file
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    # Extract text from PDF
    text = extract_text_from_pdf(filepath)

    # Generate summaries
    full_summary = summarize_text(text)
    short_summary = generate_short_summary(full_summary)

    # Pass data to the results page
    return render_template('results.html', filename=filename, full_summary=full_summary, short_summary=short_summary)

def extract_text_from_pdf(filepath):
    text = ""
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text += page.extract_text()
    return text

def summarize_text(text):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",  # Replace with "gpt-4" if needed
        messages=[
            {"role": "system", "content": "You are a helpful assistant that summarizes legal documents."},
            {"role": "user", "content": f"Summarize this legal document:\n\n{text}"}
        ],
        max_tokens=500,
        temperature=0.5  # Adjust for creativity
    )
    return response.choices[0].message["content"].strip()

def generate_short_summary(full_summary):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",  # Replace with "gpt-4" if needed
        messages=[
            {"role": "system", "content": "You are a helpful assistant that provides concise summaries."},
            {"role": "user", "content": f"Provide a one-line summary of this text:\n\n{full_summary}"}
        ],
        max_tokens=50,
        temperature=0.5  # Adjust for creativity
    )
    return response.choices[0].message["content"].strip()

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    app.run(debug=True)



@app.route('/process', methods=['POST'])
def process_files():
    if 'user' not in session:  # Ensure the user is logged in
        return redirect(url_for('login'))

    # Check if files and text input are in the request
    if 'files' not in request.files or 'searchText' not in request.form:
        return jsonify({'error': 'Files or search text missing'}), 400

    files = request.files.getlist('files')  # Get all uploaded files
    search_text = request.form.get('searchText')  # Get search text input
    results = []

    # Process each uploaded file
    for file in files:
        if file.filename == '':
            continue

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)  # Save the file temporarily

        # Extract text from the file
        file_text = extract_text_from_pdf(filepath)

        # Use OpenAI to search the file's content for the search text
        search_result = search_text_with_openai(file_text, search_text)
        results.append(f"Results for {filename}:\n{search_result}\n")

        # Optionally, delete the file after processing
        os.remove(filepath)

    # Write the results to a new file
    result_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'search_results.txt')
    with open(result_file_path, 'w') as result_file:
        result_file.write("\n".join(results))

    # Return the file for download
    return send_file(result_file_path, as_attachment=True, download_name='search_results.txt')

def search_text_with_openai(file_text, search_text):
    """
    Uses OpenAI's API to search for occurrences or related information about the `search_text` in `file_text`.
    """
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",  # Replace with "gpt-4" if desired
        messages=[
            {"role": "system", "content": "You are a helpful assistant for searching documents."},
            {"role": "user", "content": f"Search the following document for this text: '{search_text}' and provide related information:\n\n{file_text}"}
        ],
        max_tokens=1000,
        temperature=0.5
    )
    return response.choices[0].message["content"].strip()
