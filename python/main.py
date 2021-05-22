from fastapi import FastAPI, status, HTTPException, Response, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic.dataclasses import dataclass
from pydantic.json import pydantic_encoder
from typing import List, Optional
import datetime
import pickle
import os.path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import json
import logging
import uuid

app = FastAPI()
# Uncomment if need to verify google domain
#app.mount("/", StaticFiles(directory='static'))

logger = logging.getLogger(__name__)
class ScheduleRequest(BaseModel):
    interviewers: List[str]
    interviewee: str
    availableTimes: List[datetime.datetime]
    interviewLengthMins: int
    currentUser: str

@dataclass
class ItemId:
    id: str

@dataclass
class FreeBusyRequest:
    timeMin: datetime.datetime
    timeMax: datetime.datetime
    items: List[ItemId]
    timeZone: Optional[str] = None
    groupExpansionMax: Optional[int] = None
    calendarExpansionMax: Optional[int] = None


SCOPES = ['https://www.googleapis.com/auth/calendar']
HOST = os.getenv("HOST", "localhost")
#INCREMENT_MINS = datetime.timedelta(minutes=30)

@app.get("/health")
async def healthcheck():
    return {"message": "good to go"}


@app.post("/watch", status_code=status.HTTP_200_OK)
def watch(req: dict):
    print("Request", req)

@app.post("/schedule", status_code=status.HTTP_201_CREATED)
def schedule(sched_req: ScheduleRequest):
    logging.debug("Getting schedule")
    logger.debug("Getting schedule")
    print("Getting schedule")
    service = auth(sched_req.currentUser)
    interview_list = [ItemId(i) for i in sched_req.interviewers]

    found_time = False
    for s in sched_req.availableTimes:
        end_time = s + datetime.timedelta(minutes=30)
        fbr = FreeBusyRequest(timeMin=s, timeMax=end_time, items=interview_list)
        j = json.loads(json.dumps(fbr, default=pydantic_encoder))
        print('j', j)
        print('jd', j["timeMin"])
        r = service.freebusy().query(body=j).execute()
        available_interviewer = get_available_interviewer(r["calendars"])
        print("res", r)

        if available_interviewer:
            print(f"Found time slot for {available_interviewer}")
            schedule_time(service, sched_req.interviewee, available_interviewer, s, end_time)
            found_time = True
            break

    if not found_time:
        raise HTTPException(status_code=404, detail="No available time found")
    else:
        return Response(status_code=status.HTTP_200_OK)

def get_available_interviewer(i_cals: dict):
    for k, v in i_cals.items():
        if len(v['busy']) == 0:
            return k
    return None

def schedule_time(service, interviewee: str, interviewer: str, start_time: datetime.datetime, end_time: datetime.datetime ):
    start_time_str = start_time.isoformat()
    end_time_str = end_time.isoformat()

    requestId =str(uuid.uuid4())[:8]

    event = {
        'summary': 'TEST: Interview you will fail',
        'location': 'Mars',
        'description': 'Very tough interview.',
        'start': {
            'dateTime': start_time_str,
        },
        'end': {
            'dateTime': end_time_str,
        },
        'attendees': [
            {'email': interviewer},
            #{'email': interviewee},
        ],
        'conferenceData': {
            'createRequest': {
                'requestId': requestId
            }
        }
    }

    event = service.events().insert(calendarId='primary', body=event, conferenceDataVersion=1, sendUpdates='all').execute()
    print("schedule event", event)
    
    notif_channel = {
            'id': requestId,
            'type': 'web_hook',
            'address': 'https://vein.ngrok.io/watch',
    }

    notif = service.events().watch(calendarId='primary', body=notif_channel).execute()
    print(notif)


def auth(user: str):
    """Shows basic usage of the Google Calendar API.
    Prints the start and name of the next 10 events on the user's calendar.
    """
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    pickle_file_name = f'{user}.pickle'
    if os.path.exists(pickle_file_name):
        with open(pickle_file_name, 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            print('f.a', flow.authorization_url())
            creds = flow.run_local_server(host=HOST)
            print('c', creds)
        # Save the credentials for the next run
        with open(pickle_file_name, 'wb') as token:
            pickle.dump(creds, token)

    print(creds)

    service = build('calendar', 'v3', credentials=creds)
    return service

    # Call the Calendar API
    now = datetime.datetime.utcnow().isoformat() + 'Z' # 'Z' indicates UTC time
    print('Getting the upcoming 10 events')
    events_result = service.events().list(calendarId='primary', timeMin=now,
                                        maxResults=10, singleEvents=True,
                                        orderBy='startTime').execute()
    events = events_result.get('items', [])

    if not events:
        print('No upcoming events found.')
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        print(start, event['summary'])
