WELCOME_MESSAGE = """
🏢 Welcome to Abhinav Group Supplier Registration

Thank you for your interest in becoming an approved supplier.

You will be required to answer 18 questions.

⚠️ Please answer every question carefully.

Skipping mandatory information or providing incorrect information may result in rejection of your supplier registration request.

During registration you will be asked to provide:

• Company Information
• GST Details
• Banking Details
• MSME Information (Optional)
• GST Registration Certificate

💡 Note: Please answer all questions in sequence. Do not try to modify your answers or send other messages in between; you will have a full opportunity to review and correct any mistakes at the end before final submission.

To begin registration, please reply:

START
"""


REGISTRATION_STEPS = [
    "company_name",          # Q1
    "principal_business",    # Q2
    "material_types",        # Q3
    "registered_address",    # Q4
    "contact_person_name",   # Q5
    "contact_person_email",  # Q6
    "whatsapp_number",       # Q7
    "bank_name",             # Q8
    "beneficiary_name",      # Q9
    "bank_account_number",   # Q10
    "bank_ifsc",             # Q11
    "branch_name",           # Q12
    "is_msme",               # Q13
    "msme_number",           # Q14 (skipped if is_msme = NO)
    "msme_certificate_path", # Q15 (skipped if is_msme = NO)
    "gst_number",            # Q16
    "gst_certificate_path",  # Q17
    "declaration_accepted"   # Q18
]


QUESTION_MAP = {
    "company_name":
        "What is your Company Name?",

    "principal_business":
        "What work does your company do?\n\nExample:\nCement Supply\nSteel Supply\nElectrical Work",

    "material_types":
        """What materials do you supply?

Example:

Cement

Steel

Cement, Steel, Sand

Type your answer.""",

    "registered_address":
        "Please enter your Company Address",

    "contact_person_name":
        "Please enter Contact Person Name",

    "contact_person_email":
        "Please enter Email Address\n\n(Type SKIP if not available)",

    "whatsapp_number":
        "Please enter WhatsApp Number",

    "bank_name":
        "Please enter Bank Name",

    "beneficiary_name":
        "Please enter Account Holder Name",

    "bank_account_number":
        "Please enter Bank Account Number",

    "bank_ifsc":
        "Please enter IFSC Code",

    "branch_name":
        "Please enter Bank Branch Name",

    "is_msme":
        "Are you MSME Registered?\n\nReply YES or NO",

    "msme_number":
        "Please enter MSME Number\n\nOr type SKIP",

    "msme_certificate_path":
        """Please upload MSME Certificate

(PDF/JPG/PNG)

Or type SKIP""",

    "gst_number":
        "Please enter your GST Number",

    "gst_certificate_path":
        """Please upload GST Registration Certificate

(PDF/JPG/PNG)

This document is mandatory.""",

    "declaration_accepted":
        """Declaration

I confirm that all information provided is correct and true.

Reply YES to submit registration."""
}


# Human-readable labels for the summary shown before declaration
STEP_LABELS = {
    "company_name": "Company Name",
    "principal_business": "Business",
    "material_types": "Materials",
    "registered_address": "Address",
    "contact_person_name": "Contact Person",
    "contact_person_email": "Email",
    "whatsapp_number": "WhatsApp",
    "bank_name": "Bank Name",
    "beneficiary_name": "Account Holder",
    "bank_account_number": "Account Number",
    "bank_ifsc": "IFSC Code",
    "branch_name": "Bank Branch",
    "is_msme": "MSME Registered",
    "msme_number": "MSME Number",
    "msme_certificate_path": "MSME Certificate",
    "gst_number": "GST Number",
    "gst_certificate_path": "GST Certificate",
}


# Emoji numbers for dynamic prefix display
STEP_EMOJIS = [
    "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣",
    "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟",
    "1️⃣1️⃣", "1️⃣2️⃣", "1️⃣3️⃣", "1️⃣4️⃣", "1️⃣5️⃣",
    "1️⃣6️⃣", "1️⃣7️⃣", "1️⃣8️⃣"
]