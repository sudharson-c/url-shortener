import streamlit as st
import requests
from datetime import datetime
import urllib.parse
import os
import time
import streamlit.components.v1 as components

st.set_page_config(
    page_title="URL Shortener",
    layout="wide"
)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")
if not BACKEND_URL.startswith("http"):
    BACKEND_URL = f"http://{BACKEND_URL}"

# Initialize session state
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
    st.session_state.username = None
if 'urls' not in st.session_state:
    st.session_state.urls = []

st.title("URL Shortener")

# Function to fetch URLs with retry
def fetch_urls():
    for _ in range(3):
        try:
            response = requests.get(f"{BACKEND_URL}/urls", params={"user_id": st.session_state.user_id})
            if response.status_code == 200:
                st.session_state.urls = response.json()['urls']
                return
            else:
                st.error(f"Failed to fetch URLs: {response.json().get('error', 'Unknown error')}")
        except Exception as e:
            st.error(f"Error fetching URLs: {str(e)}")
        time.sleep(1)
    st.error("Failed to fetch URLs after retries")

# Function to resolve URL
def resolve_url(short_code):
    try:
        response = requests.get(f"{BACKEND_URL}/{short_code}", allow_redirects=True)
        if response.status_code == 200:
            return response.url
        else:
            st.error(response.json().get('error', 'Unknown error'))
    except Exception as e:
        st.error(f"Error resolving URL: {str(e)}")
    return None

# Login/Register UI
if not st.session_state.user_id:
    tab1, tab2 = st.tabs(["Login", "Register"])
    
    with tab1:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            if submitted:
                with st.spinner("Logging in..."):
                    try:
                        response = requests.post(f"{BACKEND_URL}/login", json={
                            "username": username,
                            "password": password
                        })
                        if response.status_code == 200:
                            st.session_state.user_id = response.json()['user_id']
                            st.session_state.username = username
                            st.success("Logged in successfully!")
                            st.experimental_rerun()
                        else:
                            st.error(response.json().get('error', 'Unknown error'))
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
    
    with tab2:
        with st.form("register_form"):
            new_username = st.text_input("New Username")
            new_password = st.text_input("New Password", type="password")
            if st.form_submit_button("Register"):
                with st.spinner("Registering..."):
                    try:
                        response = requests.post(f"{BACKEND_URL}/register", json={
                            "username": new_username,
                            "password": new_password
                        })
                        if response.status_code == 201:
                            st.success("Registered successfully! Please login.")
                        else:
                            st.error(response.json().get('error', 'Unknown error'))
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
else:
    st.sidebar.write(f"👤 Logged in as: {st.session_state.username}")
    tab1, tab2, tab3, tab4 = st.tabs(["Shorten URL", "My URLs", "Resolve URL", "Analytics"])
    
    with tab1:
        st.subheader("Shorten URL")
        with st.form("shorten_form"):
            url = st.text_input("Enter URL to shorten:", placeholder="https://example.com")
            custom_alias = st.text_input("Custom alias (optional):", placeholder="my-custom-name", help="4-20 characters, letters, numbers, hyphens only")
            submitted = st.form_submit_button("Shorten")
            
            if submitted:
                if not url:
                    st.error("Please enter a URL")
                else:
                    with st.spinner("Shortening URL..."):
                        try:
                            frontend_url = st.experimental_get_query_params().get('frontend_url', [BACKEND_URL])[0]
                            payload = {
                                "url": url,
                                "user_id": st.session_state.user_id,
                                "frontend_base_url": frontend_url
                            }
                            if custom_alias:
                                payload["custom_alias"] = custom_alias
                            
                            response = requests.post(f"{BACKEND_URL}/shorten", json=payload)
                            
                            if response.status_code == 200:
                                data = response.json()
                                st.session_state.last_shortened = {
                                    'short_url': data['short_url'],
                                    'original_url': data['original_url']
                                }
                                st.success("URL shortened successfully!")
                                fetch_urls()
                            else:
                                st.error(response.json().get('error', 'Failed to shorten URL'))
                        except Exception as e:
                            st.error(f"Error: {str(e)}")

        if 'last_shortened' in st.session_state:
            st.markdown("### Your shortened URL:")
            st.code(st.session_state.last_shortened['short_url'])
            if st.button("📋 Copy to Clipboard"):
                components.html(
                    f"""
                    <script>
                    navigator.clipboard.writeText("{st.session_state.last_shortened['short_url']}");
                    alert("Copied to clipboard!");
                    </script>
                    """
                )
                st.write("Copied to clipboard!")
    
    with tab2:
        st.subheader("My URLs")
        if st.button("🔄 Refresh URLs"):
            with st.spinner("Fetching URLs..."):
                fetch_urls()
        
        if not st.session_state.urls:
            fetch_urls()
        
        if st.session_state.urls:
            for url in st.session_state.urls:
                with st.expander(f"🔗 {url['short_url']}", expanded=False):
                    cols = st.columns([3, 1])
                    with cols[0]:
                        st.markdown(f"**Original URL:** {url['original_url']}")
                        st.markdown(f"**Short URL:** {url['full_short_url']}")
                        st.markdown(f"**Created:** {url['created_at']}")
                    with cols[1]:
                        if st.button("Delete", key=f"delete_{url['_id']}"):
                            with st.spinner("Deleting URL..."):
                                try:
                                    response = requests.delete(f"{BACKEND_URL}/urls/{url['_id']}", params={"user_id": st.session_state.user_id})
                                    if response.status_code == 200:
                                        st.success("URL deleted!")
                                        st.session_state.urls = [u for u in st.session_state.urls if u['_id'] != url['_id']]
                                        st.experimental_rerun()
                                    else:
                                        st.error(response.json().get('error', 'Failed to delete URL'))
                                except Exception as e:
                                    st.error(f"Error: {str(e)}")
        else:
            st.info("No shortened URLs yet. Create one in the 'Shorten URL' tab!")
    
    with tab3:
        st.subheader("Resolve URL")
        short_url = st.text_input("Enter short URL to resolve:")
        if st.button("Resolve"):
            if short_url:
                with st.spinner("Resolving URL..."):
                    short_path = short_url.split('/')[-1]
                    original_url = resolve_url(short_path)
                    if original_url:
                        st.success(f"Original URL: {original_url}")
            else:
                st.error("Please enter a short URL")
    
    with tab4:
        st.subheader("URL Analytics")
        if st.session_state.urls:
            selected_url = st.selectbox("Select a URL", [url['full_short_url'] for url in st.session_state.urls])
            if st.button("View Analytics"):
                with st.spinner("Fetching analytics..."):
                    short_path = selected_url.split('/')[-1]
                    try:
                        response = requests.get(f"{BACKEND_URL}/analytics/{short_path}", params={"user_id": st.session_state.user_id})
                        if response.status_code == 200:
                            data = response.json()
                            st.write(f"**Total Clicks:** {data['total_clicks']}")
                            for click in data['clicks']:
                                st.write(f"Timestamp: {click['timestamp']}, User Agent: {click['user_agent']}")
                        else:
                            st.error(response.json().get('error', 'Failed to fetch analytics'))
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
        else:
            st.info("No URLs available for analytics.")

    if st.sidebar.button("🚪 Logout"):
        st.session_state.clear()
        st.experimental_rerun()

def main():
    query_params = st.experimental_get_query_params()
    path = query_params.get('path', [None])[0]
    if path and path != "":
        original_url = resolve_url(path)
        if original_url:
            st.success(f"Original URL: {original_url}")
        else:
            st.error("Invalid or expired short URL")

if __name__ == "__main__":
    main()