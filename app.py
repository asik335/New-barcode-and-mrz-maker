import io
import os
import random
import re
import string
from datetime import date, datetime, timedelta
import pdf417gen
from PIL import Image
import streamlit as st

# Optional MRZ library for TD2/TD3 (with native fallback)
try:
    from mrz.generator.td1 import TD1CodeGenerator
    from mrz.generator.td2 import TD2CodeGenerator
    from mrz.generator.td3 import TD3CodeGenerator
    HAS_MRZ_LIB = True
except ImportError:
    HAS_MRZ_LIB = False

# Standard AAMVA Control Characters
LF, RS, CR = "\x0a", "\x1e", "\x0d"

# State to IIN Mapping (State Name: (IIN, State Code))
STATE_IIN_MAP = {
    "Alabama (AL)": ("636033", "AL"),
    "Alaska (AK)": ("636059", "AK"),
    "Arizona (AZ)": ("636026", "AZ"),
    "Arkansas (AR)": ("636021", "AR"),
    "California (CA)": ("636014", "CA"),
    "Colorado (CO)": ("636020", "CO"),
    "Connecticut (CT)": ("636006", "CT"),
    "Delaware (DE)": ("636011", "DE"),
    "District of Columbia (DC)": ("636042", "DC"),
    "Florida (FL)": ("636010", "FL"),
    "Georgia (GA)": ("636055", "GA"),
    "Hawaii (HI)": ("636047", "HI"),
    "Idaho (ID)": ("636050", "ID"),
    "Illinois (IL)": ("636035", "IL"),
    "Indiana (IN)": ("636037", "IN"),
    "Iowa (IA)": ("636018", "IA"),
    "Kansas (KS)": ("636022", "KS"),
    "Kentucky (KY)": ("636046", "KY"),
    "Louisiana (LA)": ("636007", "LA"),
    "Maine (ME)": ("636041", "ME"),
    "Maryland (MD)": ("636003", "MD"),
    "Massachusetts (MA)": ("636002", "MA"),
    "Michigan (MI)": ("636032", "MI"),
    "Minnesota (MN)": ("636038", "MN"),
    "Mississippi (MS)": ("636051", "MS"),
    "Missouri (MO)": ("636030", "MO"),
    "Montana (MT)": ("636008", "MT"),
    "Nebraska (NE)": ("636054", "NE"),
    "Nevada (NV)": ("636049", "NV"),
    "New Hampshire (NH)": ("636039", "NH"),
    "New Jersey (NJ)": ("636036", "NJ"),
    "New Mexico (NM)": ("636009", "NM"),
    "New York (NY)": ("636001", "NY"),
    "North Carolina (NC)": ("636004", "NC"),
    "North Dakota (ND)": ("636034", "ND"),
    "Ohio (OH)": ("636025", "OH"),
    "Oklahoma (OK)": ("636058", "OK"),
    "Oregon (OR)": ("636029", "OR"),
    "Pennsylvania (PA)": ("636027", "PA"),
    "Rhode Island (RI)": ("636052", "RI"),
    "South Carolina (SC)": ("636005", "SC"),
    "South Dakota (SD)": ("636031", "SD"),
    "Tennessee (TN)": ("636053", "TN"),
    "Texas (TX)": ("636015", "TX"),
    "Utah (UT)": ("636040", "UT"),
    "Vermont (VT)": ("636061", "VT"),
    "Virginia (VA)": ("636000", "VA"),
    "Washington (WA)": ("636045", "WA"),
    "West Virginia (WV)": ("636060", "WV"),
    "Wisconsin (WI)": ("636028", "WI"),
    "Wyoming (WY)": ("636062", "WY"),
    "Custom / Default": ("999999", "XX"),
}


# =============================================================================
# ALGORITHMIC IDENTIFIER GENERATORS
# =============================================================================
def generate_belgium_card_number() -> str:
    """Belgian ID Card Number (12 digits, Modulo-97)."""
    base = random.randint(1000000000, 9999999999)
    rem = base % 97
    chk = 97 if rem == 0 else rem
    b_str = str(base)
    return f"{b_str[:3]}-{b_str[3:]}-{str(chk).zfill(2)}"


def generate_belgium_national_number(dob: date, is_female: bool = False) -> str:
    """Belgian National Register Number (Rijksregisternummer) (YY.MM.DD-XXX.CC)."""
    y_str = dob.strftime("%y")
    m_str = dob.strftime("%m")
    d_str = dob.strftime("%d")

    seq = random.randint(1, 499) * 2
    if not is_female:
        seq -= 1
    seq_str = f"{seq:03d}"

    base_num = int(f"{y_str}{m_str}{d_str}{seq_str}")
    if dob.year >= 2000:
        chk = 97 - (int(f"2{y_str}{m_str}{d_str}{seq_str}") % 97)
    else:
        chk = 97 - (base_num % 97)

    return f"{y_str}.{m_str}.{d_str}-{seq_str}.{chk:02d}"


def generate_croatia_oib() -> str:
    """Croatian OIB (11 digits, ISO 7064 MOD 11, 10)."""
    digits = [random.randint(0, 9) for _ in range(10)]
    remainder = 10
    for d in digits:
        step1 = (remainder + d) % 10
        if step1 == 0:
            step1 = 10
        step2 = (step1 * 2) % 11
        remainder = step2
    chk = 11 - remainder
    if chk == 10:
        chk = 0
    return "".join(map(str, digits)) + str(chk)


def generate_spain_dni() -> str:
    """Spanish DNI (8 digits + Modulo-23 letter)."""
    num = random.randint(10000000, 99999999)
    letters = "TRWAGMYFPDXBNJZSQVHLCKE"
    return f"{num}{letters[num % 23]}"


def generate_netherlands_bsn() -> str:
    """Dutch BSN (9 digits, 11-proof / elfproef)."""
    while True:
        d = [random.randint(0, 9) for _ in range(8)]
        # 11-proof: 9*d1 + 8*d2 + 7*d3 + 6*d4 + 5*d5 + 4*d6 + 3*d7 + 2*d8 - 1*d9 == 0 (mod 11)
        total = sum(d[i] * (9 - i) for i in range(8))
        d9 = total % 11
        if d9 < 10:
            return "".join(map(str, d)) + str(d9)


def generate_poland_pesel(dob: date, is_female: bool = False) -> str:
    """Polish PESEL (11 digits with century month encoding and mod 10 weights)."""
    year, month, day = dob.year, dob.month, dob.day
    if 1800 <= year <= 1899:
        month += 80
    elif 2000 <= year <= 2099:
        month += 20
    elif 2100 <= year <= 2199:
        month += 40
    elif 2200 <= year <= 2299:
        month += 60

    y_str = f"{year % 100:02d}"
    m_str = f"{month:02d}"
    d_str = f"{day:02d}"

    seq = random.randint(0, 999)
    gender_digit = random.choice([0, 2, 4, 6, 8]) if is_female else random.choice([1, 3, 5, 7, 9])
    base = f"{y_str}{m_str}{d_str}{seq:03d}{gender_digit}"

    weights = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]
    s = sum(int(base[i]) * weights[i] for i in range(10))
    chk = (10 - (s % 10)) % 10
    return f"{base}{chk}"


def generate_sweden_pin(dob: date) -> str:
    """Swedish Personnummer (10 digits, Luhn check)."""
    date_part = dob.strftime("%y%m%d")
    seq = f"{random.randint(0, 999):03d}"
    base = date_part + seq

    total = 0
    for i, char in enumerate(base):
        n = int(char) * (2 if i % 2 == 0 else 1)
        total += (n // 10) + (n % 10)
    chk = (10 - (total % 10)) % 10
    return f"{date_part}-{seq}{chk}"


def generate_finland_hetu(dob: date, is_female: bool = False) -> str:
    """Finnish HETU (DDMMYY[+-A]NNNC, Modulo-31)."""
    d_str = dob.strftime("%d%m%y")
    century_char = "+" if dob.year < 1900 else ("-" if dob.year < 2000 else "A")
    seq = random.randint(1, 449) * 2
    if not is_female:
        seq += 1
    seq_str = f"{seq:03d}"

    check_chars = "0123456789ABCDEFHJKLMNPRSTUVWXY"
    rem = int(f"{d_str}{seq_str}") % 31
    return f"{d_str}{century_char}{seq_str}{check_chars[rem]}"


def generate_france_nir(dob: date, is_female: bool = False) -> str:
    """French NIR / Social Security Number (13 digits + 2-digit key Modulo-97)."""
    gender = "2" if is_female else "1"
    y_str = dob.strftime("%y")
    m_str = dob.strftime("%m")
    dept = f"{random.randint(1, 95):02d}"
    commune = f"{random.randint(1, 999):03d}"
    order = f"{random.randint(1, 999):03d}"

    base_str = f"{gender}{y_str}{m_str}{dept}{commune}{order}"
    key = 97 - (int(base_str) % 97)
    return f"{base_str} {key:02d}"


def generate_brazil_cpf() -> str:
    """Brazilian CPF (11 digits, Dual Modulo-11)."""
    d = [random.randint(0, 9) for _ in range(9)]
    v1 = sum(d[i] * (10 - i) for i in range(9)) % 11
    d.append(0 if v1 < 2 else 11 - v1)
    v2 = sum(d[i] * (11 - i) for i in range(10)) % 11
    d.append(0 if v2 < 2 else 11 - v2)
    s = "".join(map(str, d))
    return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"


# =============================================================================
# ICAO 9303 TD1 / TD2 / TD3 MRZ LOGIC
# =============================================================================
def get_icao_char_value(c: str) -> int:
    if c.isdigit():
        return ord(c) - 48
    if c.isalpha():
        return ord(c.upper()) - 55
    return 0


def calculate_icao_check_digit(s: str) -> str:
    weights = [7, 3, 1]
    total = sum(get_icao_char_value(c) * weights[i % 3] for i, c in enumerate(s))
    return str(total % 10)


def sanitize_mrz(s: str) -> str:
    return "".join(c.upper() if c.isalnum() else "<" for c in s)


def build_td1_mrz_with_overflow(
    doc_type: str,
    country: str,
    doc_num: str,
    dob: str,
    sex: str,
    expiry: str,
    nationality: str,
    surname: str,
    given_names: str,
    optional_data1: str = "",
    optional_data2: str = "",
) -> str:
    """Builds a strict ICAO Doc 9303 TD1 MRZ with >9 digit document overflow handling."""
    dtype = sanitize_mrz(doc_type).ljust(2, "<")[:2]
    c_code = sanitize_mrz(country).ljust(3, "<")[:3]
    raw_num = sanitize_mrz(doc_num.replace("-", "").replace(".", "").replace(" ", ""))
    dob_san = sanitize_mrz(dob).ljust(6, "<")[:6]
    sex_san = sanitize_mrz(sex).ljust(1, "<")[:1]
    exp_san = sanitize_mrz(expiry).ljust(6, "<")[:6]
    nat_code = sanitize_mrz(nationality).ljust(3, "<")[:3]

    # Handle Doc Number Overflow (>9 chars)
    if len(raw_num) > 9:
        doc_part1 = raw_num[:9]
        doc_check = "<"  # Overflow indicator chevron
        overflow = raw_num[9:]
        opt1_content = overflow + (sanitize_mrz(optional_data1) if optional_data1 else "")
        opt_field1 = opt1_content.ljust(15, "<")[:15]
    else:
        doc_part1 = raw_num.ljust(9, "<")[:9]
        doc_check = calculate_icao_check_digit(doc_part1)
        opt_field1 = sanitize_mrz(optional_data1).ljust(15, "<")[:15]

    line1 = f"{dtype}{c_code}{doc_part1}{doc_check}{opt_field1}"

    # Line 2: Personal data + Composite Checksum
    dob_check = calculate_icao_check_digit(dob_san)
    expiry_check = calculate_icao_check_digit(exp_san)
    opt_field2 = sanitize_mrz(optional_data2).ljust(11, "<")[:11]

    composite_payload = f"{doc_part1}{doc_check}{opt_field1}{dob_san}{dob_check}{exp_san}{expiry_check}{opt_field2}"
    composite_check = calculate_icao_check_digit(composite_payload)

    line2 = f"{dob_san}{dob_check}{sex_san}{exp_san}{expiry_check}{nat_code}{opt_field2}{composite_check}"

    # Line 3: Name
    name_payload = f"{sanitize_mrz(surname)}<<{sanitize_mrz(given_names)}".replace(" ", "<")
    line3 = name_payload.ljust(30, "<")[:30]

    return f"{line1}\n{line2}\n{line3}"


# =============================================================================
# AAMVA BARCODE LOGIC
# =============================================================================
def get_aamva_version_from_issue_date(issue_date_val: date) -> str:
    if issue_date_val < date(2020, 1, 1):
        return "08"
    elif issue_date_val < date(2025, 1, 1):
        return "10"
    else:
        return "11"


def get_age_at_issue(birthdate: date, issue_date_val: date) -> int:
    return issue_date_val.year - birthdate.year - (
        (issue_date_val.month, issue_date_val.day) < (birthdate.month, birthdate.day)
    )


def generate_expiration_date(state: str, birthdate: date, issue_date_val: date) -> date:
    state = state.upper().strip()
    age = get_age_at_issue(birthdate, issue_date_val)

    def calculate_bday_expiry(target_year: int) -> date:
        try:
            return date(target_year, birthdate.month, birthdate.day)
        except ValueError:
            return date(target_year, 2, 28)

    if state == "AZ":
        if age < 65:
            return calculate_bday_expiry(birthdate.year + 65)
        term = 5
    elif state == "TX":
        if age < 18:
            return calculate_bday_expiry(birthdate.year + 18)
        term = 2 if age >= 85 else 8
    elif state == "VA":
        term = 5 if age >= 75 else 8
    elif state == "HI":
        term = 2 if age >= 80 else (4 if age >= 72 else 8)
    elif state == "IL":
        term = 1 if age >= 87 else (2 if age >= 81 else 4)
    elif state == "IN":
        term = 2 if age >= 85 else (3 if age >= 75 else 6)
    elif state == "MO":
        term = 3 if (age < 21 or age >= 70) else 6
    else:
        state_terms = {
            "AL": 4, "AK": 5, "AR": 8, "CA": 5, "CO": 5, "CT": 6,
            "DE": 8, "DC": 8, "FL": 8, "GA": 8, "ID": 4, "IA": 8,
            "KS": 6, "KY": 8, "LA": 6, "ME": 6, "MD": 8, "MA": 5,
            "MI": 4, "MN": 4, "MS": 8, "MT": 8, "NE": 5, "NV": 8,
            "NH": 5, "NJ": 4, "NM": 4, "NY": 8, "NC": 8, "ND": 6,
            "OH": 4, "OK": 4, "OR": 8, "PA": 4, "RI": 5, "SC": 8,
            "SD": 5, "TN": 8, "UT": 8, "VT": 4, "WA": 6, "WV": 8,
            "WI": 8, "WY": 5,
        }
        term = state_terms.get(state, 8)

    return calculate_bday_expiry(issue_date_val.year + term)


def corrupt_raw_string(raw: str, choice: str) -> str:
    if choice == "wrong_header_version":
        idx = raw.find("ANSI ")
        if idx != -1:
            ver_idx = idx + 11
            return raw[:ver_idx] + "77" + raw[ver_idx + 2:]
    elif choice == "truncated_subfile":
        return raw[: int(len(raw) * 0.7)]
    elif choice == "bad_offset_length":
        idx = raw.find("DL", 15)
        if idx != -1:
            return raw[: idx + 2] + "9999" + "9999" + raw[idx + 10:]
    elif choice == "missing_mandatory_field":
        lines = raw.split(LF)
        lines = [l for l in lines if not l.startswith("DAQ")]
        return LF.join(lines)
    elif choice == "bad_separators":
        return raw.replace(LF, "|").replace(CR, "#")
    elif choice == "swapped_dob_expiry":
        dbb_match = re.search(r"DBB([^\x0a\x0d\x1e]+)", raw)
        dba_match = re.search(r"DBA([^\x0a\x0d\x1e]+)", raw)
        if dbb_match and dba_match:
            dob_val = dbb_match.group(1)
            exp_val = dba_match.group(1)
            raw = raw.replace(f"DBB{dob_val}", f"DBB{exp_val}_TEMP")
            raw = raw.replace(f"DBA{exp_val}", f"DBA{dob_val}")
            raw = raw.replace(f"DBB{exp_val}_TEMP", f"DBB{exp_val}")
    return raw


# =============================================================================
# STREAMLIT UI SETUP
# =============================================================================
st.set_page_config(page_title="Document Tools & MRZ Suite", page_icon="🪪", layout="centered")
st.title("🪪 Document Tools & Verification Suite")

tab_barcode, tab_mrz, tab_national_ids = st.tabs([
    "📊 PDF417 Barcode Generator",
    "🔤 Advanced MRZ Generator (9+ Overflow)",
    "🌍 National ID & Number Generators",
])

# Initialize session state defaults
defaults_dict = {
    "mrz_sur": "DAVIS",
    "mrz_given": "RACHEL",
    "mrz_num": "591741658365",
    "mrz_personal": "",
    "mrz_country": "BEL",
    "mrz_nat": "BEL",
    "mrz_dob": "920119",
    "mrz_exp": "290412",
    "mrz_sex": "F",
}
for k, v in defaults_dict.items():
    if k not in st.session_state:
        st.session_state[k] = v


# =============================================================================
# TAB 1: AAMVA PDF417 BARCODE GENERATOR
# =============================================================================
with tab_barcode:
    selected_state = st.selectbox(
        "Select State (Auto-fills IIN & State Code)", list(STATE_IIN_MAP.keys())
    )
    default_iin, default_state_code = STATE_IIN_MAP[selected_state]
    iin = st.text_input("IIN Number", value=default_iin)

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Personal Info")
        first_name = st.text_input("First Name (DAC)", "JOHN")
        last_name = st.text_input("Last Name (DCS)", "DOE")
        middle_name = st.text_input("Middle Name (DAD)", "NONE")
        dob = st.text_input("DOB MMDDYYYY (DBB)", "01011995")
        gender = st.selectbox(
            "Gender (DBC)",
            options=["1", "2", "9"],
            format_func=lambda x: {"1": "1 - Male", "2": "2 - Female", "9": "9 - Non-binary"}[x],
        )
        eye_color = st.text_input("Eye Color (DAY)", "BRO")
        hair_color = st.text_input("Hair Color (DAZ)", "BRN")
        height = st.text_input("Height (DAU)", "070 in")
        weight = st.text_input("Weight lbs (DAW)", "180 lb")
        organ_donor = st.selectbox("Organ Donor (DDK)", ["1", "2", "0"])
        veteran = st.selectbox("Veteran (DDL)", ["0", "1", "2"])

    with col2:
        st.subheader("Document & Address Info")
        license_num = st.text_input("License Number (DAQ)", "D12345678")
        doc_disc = st.text_input("Document Discriminator (DCF)", "123456789")
        dda = st.text_input("Compliance Type (DDA)", "F")
        street = st.text_input("Street (DAG)", "123 MAIN ST")
        city = st.text_input("City (DAI)", "ANYTOWN")
        state_code = st.text_input("State Code (DAJ)", value=default_state_code)
        postal_code = st.text_input("Postal Code (DAK)", "123450000")
        issue_date = st.text_input("Issue Date MMDDYYYY (DBD)", "01012025")

        auto_calc_exp = st.checkbox("⚡ Auto-Calculate Expiry Date", value=True)
        calculated_expiry_val = "01012033"
        parsed_issue_dt = None
        try:
            dob_dt = datetime.strptime(dob.strip(), "%m%d%Y").date()
            parsed_issue_dt = datetime.strptime(issue_date.strip(), "%m%d%Y").date()
            if auto_calc_exp:
                calculated_expiry_val = generate_expiration_date(state_code, dob_dt, parsed_issue_dt).strftime("%m%d%Y")
        except ValueError:
            pass

        expiry_date = st.text_input("Expiry Date MMDDYYYY (DBA)", value=calculated_expiry_val, disabled=auto_calc_exp)
        vehicle_class = st.text_input("Vehicle Class (DCA)", "C")
        restrictions = st.text_input("Restrictions (DCB)", "NONE")
        endorsements = st.text_input("Endorsements (DCD)", "NONE")

    st.divider()
    auto_version = st.checkbox("⚡ Auto-Detect AAMVA Version from Issue Date", value=True)
    detected_version = "11"
    if parsed_issue_dt:
        detected_version = get_aamva_version_from_issue_date(parsed_issue_dt)

    aamva_version = st.selectbox(
        "AAMVA Header Version",
        options=["08 (2013 Standard)", "10 (2020 Standard)", "11 (2025 Standard)"],
        index={"08": 0, "10": 1, "11": 2}[detected_version],
        disabled=auto_version,
    ).split(" ")[0]

    opt_col1, opt_col2 = st.columns(2)
    with opt_col1:
        barcode_size = st.selectbox("Barcode Output Size", ["Standard DL Size (Compact)", "Large / High-Res"])
    with opt_col2:
        malform_choice = st.selectbox(
            "Malformation Type",
            [
                "none (valid record)",
                "wrong_header_version",
                "truncated_subfile",
                "bad_offset_length",
                "missing_mandatory_field",
                "bad_separators",
                "swapped_dob_expiry",
            ],
        )

    elements = {
        "DCA": vehicle_class.upper(),
        "DCB": restrictions.upper(),
        "DCD": endorsements.upper(),
        "DBA": expiry_date,
        "DCS": last_name.upper(),
        "DAC": first_name.upper(),
        "DAD": (middle_name or "NONE").upper(),
        "DBD": issue_date,
        "DBB": dob,
        "DBC": gender,
        "DAY": eye_color.upper(),
        "DAZ": hair_color.upper(),
        "DAU": height,
        "DAW": weight,
        "DAG": street.upper(),
        "DAI": city.upper(),
        "DAJ": state_code.upper(),
        "DAK": postal_code,
        "DAQ": license_num.upper(),
        "DCF": doc_disc or license_num,
        "DCG": "USA",
        "DDA": dda.upper(),
        "DDK": organ_donor,
        "DDL": veteran,
    }

    if st.button("Generate Barcode", type="primary", use_container_width=True):
        if not iin.strip().isdigit() or len(iin.strip()) != 6:
            st.error("Error: IIN must be exactly a 6-digit number.")
        else:
            body = "DL" + "".join(f"{k}{v}{LF}" for k, v in elements.items()) + RS
            header = f"@{LF}{RS}{CR}ANSI {iin.strip()}{aamva_version}0001"
            designator = f"DL{len(header) + 10:04d}{len(body):04d}"
            raw_str = header + designator + body + CR

            if malform_choice != "none (valid record)":
                raw_str = corrupt_raw_string(raw_str, malform_choice)

            try:
                scale, ratio = (2, 3) if barcode_size.startswith("Standard") else (3, 3)
                codes = pdf417gen.encode(raw_str, columns=13, security_level=5)
                img = pdf417gen.render_image(codes, scale=scale, ratio=ratio)
                st.image(img, caption=f"Generated Barcode ({aamva_version} Standard)")

                buf = io.BytesIO()
                img.save(buf, format="PNG")
                c_dl1, c_dl2 = st.columns(2)
                c_dl1.download_button("📥 Download Image (.png)", buf.getvalue(), "aamva_barcode.png", "image/png", use_container_width=True)
                c_dl2.download_button("📄 Download Raw Text (.txt)", raw_str, "aamva_raw.txt", "text/plain", use_container_width=True)
            except Exception as e:
                st.error(f"Barcode generation error: {e}")


# =============================================================================
# TAB 2: ADVANCED MRZ GENERATOR (ICAO 9303 + 9+ DIGIT OVERFLOW)
# =============================================================================
with tab_mrz:
    st.subheader("ICAO Doc 9303 Machine Readable Zone (MRZ)")

    def generate_random_mrz_data():
        surnames = ["SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES", "GARCIA", "MILLER", "DAVIS"]
        given_names = ["JAMES", "MARY", "ROBERT", "PATRICIA", "JOHN", "JENNIFER", "MICHAEL", "LINDA"]
        countries = ["USA", "CAN", "GBR", "DEU", "FRA", "AUS", "BEL", "HRV", "ESP"]

        doc_num = "".join(random.choices(string.ascii_uppercase + string.digits, k=12))
        dob_dt = datetime.now() - timedelta(days=random.randint(20 * 365, 60 * 365))
        exp_dt = datetime.now() + timedelta(days=random.randint(1 * 365, 10 * 365))

        st.session_state["mrz_sur"] = random.choice(surnames)
        st.session_state["mrz_given"] = random.choice(given_names)
        st.session_state["mrz_num"] = doc_num
        st.session_state["mrz_personal"] = "".join(random.choices(string.digits, k=6))
        country = random.choice(countries)
        st.session_state["mrz_country"] = country
        st.session_state["mrz_nat"] = country
        st.session_state["mrz_dob"] = dob_dt.strftime("%y%m%d")
        st.session_state["mrz_exp"] = exp_dt.strftime("%y%m%d")
        st.session_state["mrz_sex"] = random.choice(["M", "F"])

    if st.button("🎲 Auto-Generate Random MRZ Profile", use_container_width=True):
        generate_random_mrz_data()
        st.rerun()

    st.divider()

    col_format1, col_format2 = st.columns(2)
    with col_format1:
        mrz_standard = st.selectbox(
            "MRZ Standard",
            [
                "TD1 (ID Cards - 3 Lines) [Supports 9+ digit overflow]",
                "TD2 (Large Cards/Visas - 2 Lines)",
                "TD3 (Passports - 2 Lines)",
            ],
        )
    with col_format2:
        doc_type_code = st.selectbox(
            "Document Type Code",
            ["I (Identity Card)", "P (Passport)", "A (Residence Permit)", "C (Card)", "V (Visa)"],
        )

    col1_mrz, col2_mrz = st.columns(2)
    with col1_mrz:
        mrz_surname = st.text_input("Surname / Last Name", key="mrz_sur")
        mrz_given_names = st.text_input("Given Names", key="mrz_given")
        mrz_doc_number = st.text_input("Document / Card Number (Supports 9+ digits)", key="mrz_num")
        mrz_personal_num = st.text_input("Optional / Personal Number", key="mrz_personal")
        mrz_country = st.text_input("Issuing Country (3-letter ISO)", key="mrz_country").upper()

    with col2_mrz:
        mrz_dob = st.text_input("DOB (YYMMDD)", key="mrz_dob")
        mrz_expiry = st.text_input("Expiry Date (YYMMDD)", key="mrz_exp")
        mrz_sex = st.selectbox("Sex", ["F", "M", "X"], key="mrz_sex")
        mrz_nationality = st.text_input("Nationality (3-letter ISO)", key="mrz_nat").upper()

    if st.button("Generate MRZ Text", type="primary", use_container_width=True):
        try:
            c_code = mrz_country.strip()[:3].upper()
            n_code = mrz_nationality.strip()[:3].upper()
            s_name = mrz_surname.strip().upper()
            g_name = mrz_given_names.strip().upper()
            doc_num = mrz_doc_number.strip().upper()
            pers_num = mrz_personal_num.strip().upper()
            dtype = doc_type_code.split(" ")[0]

            if "TD1" in mrz_standard:
                # Built-in strict TD1 generator with >9 digit overflow support
                mrz_result = build_td1_mrz_with_overflow(
                    doc_type=dtype,
                    country=c_code,
                    doc_num=doc_num,
                    dob=mrz_dob,
                    sex=mrz_sex,
                    expiry=mrz_expiry,
                    nationality=n_code,
                    surname=s_name,
                    given_names=g_name,
                    optional_data1=pers_num,
                )
            elif "TD2" in mrz_standard and HAS_MRZ_LIB:
                mrz_result = str(
                    TD2CodeGenerator(
                        document_type=dtype,
                        country_code=c_code,
                        surname=s_name,
                        given_names=g_name,
                        document_number=doc_num[:9],
                        nationality=n_code,
                        birth_date=mrz_dob,
                        sex=mrz_sex,
                        expiry_date=mrz_expiry,
                        optional_data=pers_num,
                        force=True,
                    )
                )
            elif "TD3" in mrz_standard and HAS_MRZ_LIB:
                mrz_result = str(
                    TD3CodeGenerator(
                        document_type=dtype,
                        country_code=c_code,
                        surname=s_name,
                        given_names=g_name,
                        document_number=doc_num[:9],
                        nationality=n_code,
                        birth_date=mrz_dob,
                        sex=mrz_sex,
                        expiry_date=mrz_expiry,
                        optional_data=pers_num,
                        force=True,
                    )
                )
            else:
                mrz_result = build_td1_mrz_with_overflow(
                    dtype, c_code, doc_num, mrz_dob, mrz_sex, mrz_expiry, n_code, s_name, g_name, pers_num
                )

            st.subheader("Generated MRZ Text")
            st.code(mrz_result, language="text")
            st.download_button(
                "📄 Download MRZ Text (.txt)",
                data=mrz_result,
                file_name=f"mrz_{doc_num}.txt",
                mime="text/plain",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"MRZ Generation Failed: {e}")


# =============================================================================
# TAB 3: NATIONAL ID & DOCUMENT NUMBER GENERATORS
# =============================================================================
with tab_national_ids:
    st.subheader("Algorithmic National ID & Identifier Generators")
    st.caption("Generates mathematically verified national IDs using official checksum algorithms.")

    def set_to_mrz(doc_val: str, country_code: str):
        cleaned = doc_val.replace("-", "").replace(".", "").replace(" ", "").strip()
        st.session_state["mrz_num"] = cleaned
        st.session_state["mrz_country"] = country_code
        st.session_state["mrz_nat"] = country_code
        st.success(f"Copied '{cleaned}' ({country_code}) to MRZ Generator tab!")

    id_col1, id_col2 = st.columns(2)

    with id_col1:
        # Belgium Card Number
        st.markdown("#### 🇧🇪 Belgium: ID Card Number")
        be_card = generate_belgium_card_number()
        st.code(be_card, language="text")
        if st.button("Use Belgium Card in MRZ", key="btn_be_card", use_container_width=True):
            set_to_mrz(be_card, "BEL")

        # Croatia OIB
        st.markdown("#### 🇭🇷 Croatia: OIB (ISO 7064 MOD 11, 10)")
        hr_oib = generate_croatia_oib()
        st.code(hr_oib, language="text")
        if st.button("Use Croatia OIB in MRZ", key="btn_hr_oib", use_container_width=True):
            set_to_mrz(hr_oib, "HRV")

        # Spain DNI
        st.markdown("#### 🇪🇸 Spain: DNI (Modulo 23)")
        es_dni = generate_spain_dni()
        st.code(es_dni, language="text")
        if st.button("Use Spain DNI in MRZ", key="btn_es_dni", use_container_width=True):
            set_to_mrz(es_dni, "ESP")

        # Netherlands BSN
        st.markdown("#### 🇳🇱 Netherlands: BSN (11-Proof Elfproef)")
        nl_bsn = generate_netherlands_bsn()
        st.code(nl_bsn, language="text")
        if st.button("Use Netherlands BSN in MRZ", key="btn_nl_bsn", use_container_width=True):
            set_to_mrz(nl_bsn, "NLD")

        # Sweden Personnummer
        st.markdown("#### 🇸🇪 Sweden: Personnummer (Luhn)")
        se_pin = generate_sweden_pin(date(1995, 8, 20))
        st.code(se_pin, language="text")
        if st.button("Use Sweden PIN in MRZ", key="btn_se_pin", use_container_width=True):
            set_to_mrz(se_pin, "SWE")

    with id_col2:
        # Belgium National Register Number
        st.markdown("#### 🇧🇪 Belgium: National Number (Rijksregisternummer)")
        be_nat = generate_belgium_national_number(date(1992, 1, 19), is_female=True)
        st.code(be_nat, language="text")
        if st.button("Use Belgium National No in MRZ", key="btn_be_nat", use_container_width=True):
            set_to_mrz(be_nat, "BEL")

        # Poland PESEL
        st.markdown("#### 🇵🇱 Poland: PESEL (Modulo 10)")
        pl_pesel = generate_poland_pesel(date(1994, 5, 14), is_female=False)
        st.code(pl_pesel, language="text")
        if st.button("Use Poland PESEL in MRZ", key="btn_pl_pesel", use_container_width=True):
            set_to_mrz(pl_pesel, "POL")

        # Finland HETU
        st.markdown("#### 🇫🇮 Finland: HETU (Modulo 31)")
        fi_hetu = generate_finland_hetu(date(1990, 11, 23), is_female=True)
        st.code(fi_hetu, language="text")
        if st.button("Use Finland HETU in MRZ", key="btn_fi_hetu", use_container_width=True):
            set_to_mrz(fi_hetu, "FIN")

        # France NIR
        st.markdown("#### 🇫🇷 France: NIR / Social Security (Modulo 97)")
        fr_nir = generate_france_nir(date(1988, 3, 12), is_female=False)
        st.code(fr_nir, language="text")
        if st.button("Use France NIR in MRZ", key="btn_fr_nir", use_container_width=True):
            set_to_mrz(fr_nir, "FRA")

        # Brazil CPF
        st.markdown("#### 🇧🇷 Brazil: CPF (Dual Modulo 11)")
        br_cpf = generate_brazil_cpf()
        st.code(br_cpf, language="text")
        if st.button("Use Brazil CPF in MRZ", key="btn_br_cpf", use_container_width=True):
            set_to_mrz(br_cpf, "BRA")
