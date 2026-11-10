#driver.py
from socket import *
import json
import base64
import os

#reads the image file and packs it into the message (base64). The file has to be small enough for ONE message.
def headshotPayload(path):
    path = path.strip().strip('"')
    try:
        with open(path, "rb") as imageFile:
            raw = imageFile.read()
    except OSError:
        print("File not found, skipping the headshot upload.")
        return json.dumps({"headshot": "", "data": ""})
    if len(raw) > 6000:
        print("File is too big for one message (max 6000 bytes), skipping the headshot upload.")
        return json.dumps({"headshot": "", "data": ""})
    return json.dumps({"headshot": os.path.basename(path), "data": base64.b64encode(raw).decode("ascii")})

#sets up the UDP client socket and connects to the server
serverName = 'localhost'
serverPort = 12000
clientSocket = socket(AF_INET, SOCK_DGRAM)
serverAddress = (serverName, serverPort)

login = False

# prompts the user for their username and password, sends the login information to the server,
#  and waits for a response. If the login is successful, it proceeds to send an acknowledgment
#  message to the server and enters a loop to receive messages from the server and respond 
# accordingly.
while not login:
    user_id = input('Input username: ')
    password = input('Input password: ')
    tag = "driver"

    #creates a JSON payload with the user's login information and sends it to the server
    payload = json.dumps({
        "id": user_id,
        "password": password,
        "tag": tag
    })

    clientSocket.sendto(payload.encode("utf-8"),serverAddress)

    #receives the server's response and decodes it from bytes to a string
    response, _  = clientSocket.recvfrom(2048)
    response = response.decode("utf-8")


    if response == "passVerified":
        login = True
    else:
        print("Login Failed")
        print("1) Try again")
        print("2) Quit")
        choice = input('Choose 1 or 2: ').strip()
        while choice not in ("1", "2"):
            choice = input('Please choose 1 or 2: ').strip()
        if choice == "2":
            raise SystemExit

print ("Login Successful")

text = "ack"
payload = json.dumps({
    "text": text
})
clientSocket.sendto(payload.encode("utf-8"), serverAddress)

#enters a loop to continuously receive messages from the server and respond accordingly. 
# It waits for a message from the server, decodes it, and checks if it is a "kill" message.
#  If it is, the loop breaks and the program ends. Otherwise, it prints the message and 
# prompts the user for input. The user's input is then sent back to the server as a JSON payload.
while True:
    response, _ = clientSocket.recvfrom(2048)
    
    response = response.decode("utf-8")
    if response == "kill":
        break
    if response == "What is your current zone? (1, 2, ..., 9)":
        print(response)
        current_zone = input('Input current zone (1, 2, ..., 9): ')
        payload = json.dumps({
            "currentZone": current_zone
        })
        clientSocket.sendto(payload.encode("utf-8"), serverAddress)
        continue
    if response == "Please upload your driver headshot.":
        print(response)
        headshot = input('Input headshot file path: ')
        payload = headshotPayload(headshot)
        clientSocket.sendto(payload.encode("utf-8"), serverAddress)
        continue
    #  answer the "pick a ride" prompt with a ride ID (R = refresh, Q = quit)
    if response.__contains__("Enter the ride ID to accept"):
        print(response)
        ride_id = input('Ride ID to accept (R to refresh, Q to quit): ')
        payload = json.dumps({
            "rideId": ride_id
        })
        clientSocket.sendto(payload.encode("utf-8"), serverAddress)
        continue
    if response.__contains__("Sorry, ride"):
        print(response)
        continue

    # final message after dropoff, just print it
    if response.__contains__("is done"):
        print(response)
        continue

    #prints the received message and prompts the user for input
    print(response)
    text = input('YES if you want to proceed: ')
    payload = json.dumps({
        "text": text
    })
    clientSocket.sendto(payload.encode("utf-8"), serverAddress)