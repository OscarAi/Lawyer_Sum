import os
import logging
from flask import Flask, request, render_template, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
import pdfplumber
import openai
from dotenv import load_dotenv

# Initialize Flask app
app = Flask(__name__)

# Configure upload folder
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'uploads')

# Ensure the folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Load environment variables from .env
load_dotenv()

# Set OpenAI API Key
openai.api_key = os.getenv('OPENAI_API_KEY')

# Flask secret key for session management
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'supersecretkey')

# Configure SQLAlchemy database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')

# Define User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(150), nullable=False)

# Create the database
with app.app_context():
    db.create_all()

# Helper function to process a single file
import time

def extract_text_from_pdf(file):
    # Extract text from a PDF file
    with pdfplumber.open(file) as pdf:
        return " ".join([page.extract_text() for page in pdf.pages if page.extract_text()])



def summarize_text(text):
    try:
        max_chunk_size = 3000  # Adjust chunk size to fit OpenAI token limits
        chunks = [text[i:i+max_chunk_size] for i in range(0, len(text), max_chunk_size)]

        full_summary = ""
        for i, chunk in enumerate(chunks, start=1):
            logging.info(f"Sending chunk {i}/{len(chunks)} to OpenAI API...")
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": chunk}
                ],
                max_tokens=500
            )
            # Correct access to the response object
            if response.choices:
                full_summary += response.choices[0].message['content'].strip() + " "
        return full_summary.strip()
    except openai.error.OpenAIError as e:
        logging.error(f"OpenAI API Error: {e}")
        return "An error occurred while summarizing the document."


def process_files_concurrently(files, search_text):
    # Combine file texts and search text, then summarize
    with ThreadPoolExecutor() as executor:
        file_texts = list(executor.map(extract_text_from_pdf, files))

    combined_text = "\n".join(file_texts)
    combined_text_with_search = f"User Input: {search_text}\n\n{combined_text}"
    combined_summary = summarize_text(combined_text_with_search)

    result = {
        'filename': "Combined Summary",
        'summary': combined_summary,
    }
    return [result]

def generate_short_summary(full_summary):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that provides concise summaries."},
                {"role": "user", "content": f"Provide a one-line summary of this text:\n\n{full_summary}"}
            ],
            max_tokens=50,
            temperature=0.5
        )
        return response['choices'][0]['message']['content'].strip()
    except openai.error.OpenAIError as e:
        logging.error(f"OpenAI API Error: {e}")
        return "An error occurred while generating the short summary."

def process_file(file):
    try:
        start_time = time.time()

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        logging.info(f"File {filename} saved. Starting text extraction...")
        # Extract text
        file_text = extract_text_from_pdf(filepath)

        logging.info(f"Text extracted from {filename}. Starting summarization...")
        # Summarize text
        full_summary = summarize_text(file_text)

        logging.info(f"Summarization completed for {filename}. Starting short summary...")
        short_summary = generate_short_summary(full_summary)

        # Remove the file after processing
        os.remove(filepath)

        end_time = time.time()
        logging.info(f"Processing for {filename} completed in {end_time - start_time:.2f} seconds.")

        return {
            'filename': filename,
            'short_summary': short_summary,
            'full_summary': full_summary,
        }
    except Exception as e:
        logging.error(f"Error processing file {file.filename}: {e}")
        return {
            'filename': file.filename,
            'short_summary': "Error processing this file.",
            'full_summary': "",
        }

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
        flash("No file uploaded.")
        return redirect(url_for('index'))

    file = request.files['file']
    if file.filename == '':
        flash("No selected file.")
        return redirect(url_for('index'))

    # Process the single file
    result = process_file(file)

    # Pass data to the results page
    return render_template('results.html', results=[result])

# Route: Process Multiple Files
from concurrent.futures import ThreadPoolExecutor

# @app.route('/process', methods=['POST'])
# def process_files():
#     try:
#         if 'user' not in session:
#             flash("Please log in to access this page.")
#             return redirect(url_for('login'))

#         if 'files' not in request.files or 'searchText' not in request.form:
#             flash("Please upload files and enter search text.")
#             return redirect(url_for('FreeSpeechSum'))

#         files = request.files.getlist('files')
#         search_text = request.form.get('searchText')

#         if not files:
#             flash("No files uploaded.")
#             return redirect(url_for('FreeSpeechSum'))

#         combined_text = ""
#         results = []

#         # Process files concurrently
#         def process_file_and_extract_text(file):
#             filename = secure_filename(file.filename)
#             filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
#             file.save(filepath)

#             logging.info(f"Processing file: {filename}")
#             file_text = extract_text_from_pdf(filepath)
#             os.remove(filepath)  # Clean up the file after processing
#             return f"\n\n--- Content from {filename} ---\n\n{file_text}"

#         with ThreadPoolExecutor() as executor:
#             # Process each file concurrently and collect their texts
#             file_texts = list(executor.map(process_file_and_extract_text, files))

#         # Combine all file texts
#         combined_text = "\n".join(file_texts)

#         # Add user input (search text) to the combined content
#         combined_text_with_search = f"User Input: {search_text}\n\n{combined_text}"

#         # Generate a single combined summary
#         combined_summary = summarize_text(combined_text_with_search)

#         # Prepare the result for rendering
#         result = {
#             'filename': "Combined Summary",
#             'short_summary': generate_short_summary(combined_summary),
#             'full_summary': combined_summary,
#         }

#         return render_template('results.html', results=[result])

#     except Exception as e:
#         logging.error(f"Error processing files: {e}")
#         flash("An error occurred while processing your files.")
#         return redirect(url_for('FreeSpeechSum'))

# Helper functions

    
@app.route('/process', methods=['POST'])
def process_files():
    if 'user' not in session:
        flash("Please log in to access this page.")
        return redirect(url_for('login'))

    files = request.files.getlist('files')
    search_text = request.form.get('searchText')

    if not files or not search_text:
        flash("No files uploaded or search text missing.")
        return redirect(url_for('index'))

    results = process_files_concurrently(files, search_text)
    
    # Debug: Print the results to check
    logging.debug(f"Results: {results}")

    return render_template('FreeSpeechResults.html', results=results)

# Main entry point
if __name__ == '__main__':
    app.run(debug=True)
