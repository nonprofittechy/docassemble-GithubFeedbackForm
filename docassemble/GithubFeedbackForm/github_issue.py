import importlib
import json
import requests
import uuid
from typing import Optional
from docassemble.base.util import log, get_config, interview_url, DARedis

# reference: https://gist.github.com/JeffPaine/3145490
# https://docs.github.com/en/free-pro-team@latest/rest/reference/issues#create-an-issue

# Authentication for user filing issue (must have read/write access to
# repository to add issue to)
__all__ = ['valid_github_issue_config', 'make_github_issue', 'save_session_info', 'set_session_github_url', 'feedback_link', 'redis_feedback_key']
USERNAME = get_config('github issues',{}).get('username')
TOKEN = get_config('github issues',{}).get('token')

redis_feedback_key = 'docassemble-GithubFeedbackForm:feedback_info'

def valid_github_issue_config():
  return bool(TOKEN)

def feedback_link(user_info_object=None, 
                   i:str=None, 
                   github_repo:str=None, 
                   github_user:str=None, 
                   variable:str=None, 
                   question_id:str=None,
                   package_version:str=None,
                   filename:str=None)->str:
  """
  Helper function to get a link to the GitHub feedback form.
  For simple usage, it should be enough to call
  `feedback_link(user_info(), github_user="MY_USER_OR_ORG_ON_GITHUB")`, so long as the package you
  want to provide feedback on exists on GitHub and you are running from an "installed" (not playground)
  link.
  """
  if user_info_object:
    package_name = str(user_info_object.package)
    # TODO: we can use the packages table or /api/packages to get the exact GitHub URL
    if package_name and not package_name.startswith("docassemble-playground"):
      _github_repo = package_name.replace('.','-')
    else:
      _github_repo = "demo" # default repo on GitHub of suffolklitlab-issues/demo for documentation purposes
    _variable = user_info_object.variable
    _question_id = user_info_object.question_id
    _filename = user_info_object.filename
    try:
      _package_version = str(importlib.import_module(user_info_object.package).__version__)
    except:
      _package_version = "playground"
    if get_config('github issues',{}).get('default repository owner'):
      _github_user = get_config('github issues',{}).get('default repository owner')
    _session_id = user_info_object.session
  
  # Allow keyword params to override any info from the user_info() object
  # We will try pulling the repo owner name from the Docassemble config
  if github_repo and github_user:
    _github_repo = github_repo
    _github_user = github_user
  elif get_config('github issues',{}).get('default repository owner') and github_repo:
    _github_user = get_config('github issues',{}).get('default repository owner')
    _github_repo = github_repo
  else:
    _github_repo = "demo"
    _github_user = "suffolklitlab-issues"
  if variable:
    _variable = variable
  if question_id:
    _question_id = question_id
  if package_version:
    _package_version = package_version  
  if filename:
    _filename = filename
  
  if not i:
    i = "docassemble.GithubFeedbackForm:feedback.yml"

  return interview_url(i=i, 
    github_repo=_github_repo, 
    github_user=_github_user, 
    variable=_variable, 
    question_id=_question_id, 
    package_version=_package_version, 
    filename=_filename,
    session_id=_session_id,
    local=False,reset=1)

def save_session_info(interview=None, session_id=None, template=None, body=None) -> Optional[dict]:
    """Saves session information along with the feedback in a redis DB"""
    if template:
      body = template.content

    if interview and session_id:
      red = DARedis()
      guid_map = red.get_data(redis_feedback_key)
      if not guid_map:
        guid_map = {}

      uuid_for_session = str(uuid.uuid4())
      guid_map[uuid_for_session] = {'interview': interview, 'session_id': session_id, 'body': body}
      red.set_data(redis_feedback_key, guid_map)
      return uuid_for_session
    else: # can happen if the forwarding interview didn't pass session info
      return None

def set_session_github_url(uuid_for_session:str, github_url:str) -> bool:
    """Returns true if save was successful"""
    red = DARedis()
    guid_map = red.get_data(redis_feedback_key)
    if not guid_map:
      guid_map = {}

    if uuid_for_session in guid_map:
      guid_map[uuid_for_session]['html_url'] = github_url
      red.set_data(redis_feedback_key, guid_map)
      return True
    else:
      log(f'Cannot find {uuid_for_session} in redis DB')
      return False

def make_github_issue(repo_owner, repo_name, template=None, title=None, body=None, label=None) -> Optional[str]:
    """
    Create a new Github issue and return the URL.

    template - the docassemble template for the github issue. Overrides `title` and `body` if provided.
    title - the title for the github issue
    body - the body of the github issue
    """
    make_issue_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues"
    # Headers
    if not TOKEN:
      log("Error creating issues: No valid GitHub token provided.")
      return None
    
    headers = {
        "Authorization": "token %s" % TOKEN,
        "Accept": "application/vnd.github.v3+json"
    }

    if label:
      labels_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/labels"
      has_label_resp = requests.request("GET", labels_url + "/" + label, headers=headers)
      if has_label_resp.status_code == 404:
        label_data = {"name": label, "description": "Feedback from a Docassemble Interview", "color": "002E60"}
        make_label_resp = requests.post(labels_url, data=label_data, headers=headers)
        if make_label_resp.status_code != 201:
          log(f'Was not able to find nor create the {label} label: {make_label_resp.content}')
          label = None

    if template:
      title = template.subject
      body = template.content
    # Create our issue
    data = {'title': title,
            'body': body,
           }
    if label:
      data['labels'] = [label]

    payload = json.dumps(data)

    # Add the issue to our repository
    response = requests.request("POST", make_issue_url, data=payload, headers=headers)
    if response.status_code == 201:
        return response.json().get('html_url')
    else:
        log(f'Could not create Issue "{title}", results {response.content}')