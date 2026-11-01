from socket import *
import json

#sets up the UDP client socket and connects to the server
serverName = 'localhost'
serverPort = 12000
clientSocket = socket(AF_INET, SOCK_DGRAM)
serverAddress = (serverName, serverPort)

login = False

# prompts the user for their username and password, sends the login information to the server, 
# and waits for a response. If the login is successful, it proceeds to send an acknowledgment 
# message to the server and enters a loop to receive messages from the server and respond accordingly.
while not login:
    user_id = input('Input username: ')
    password = input('Input password: ')

    #creates a JSON payload with the user's login information and sends it to the server
    payload = json.dumps({
        "id": user_id,
        "password": password
    })

    clientSocket.sendto(payload.encode("utf-8"),serverAddress)

    #receives the server's response and decodes it from bytes to a string
    response, _  = clientSocket.recvfrom(2048)
    response = response.decode("utf-8")


    if response == "passVerified":
        login = True
    else:
        print("Login Failed")

print ("Login Successful")

text = "ack"
payload = json.dumps({
    "text": text
})
clientSocket.sendto(payload.encode("utf-8"), serverAddress)

#enters a loop to continuously receive messages from the server and respond accordingly. 
# It waits for a message from the server, decodes it, and checks if it is a "kill" message. 
# If it is, the loop breaks and the program ends. Otherwise, it prints the message and prompts 
# the user for input. The user's input is then sent back to the server as a JSON payload.
while True:
    response, _ = clientSocket.recvfrom(2048)
    
    response = response.decode("utf-8")
    if response == "kill":
        break
    if response == "What is your desired pickup and dropoff zone? Pickup zone: 1, Dropoff zone: 2":
        print(response)
        pickup_zone = input('Input pickup zone (1, 2, ..., 9): ')
        dropoff_zone = input('Input dropoff zone (1, 2, ..., 9): ')
        payload = json.dumps({
            "pickupZone": pickup_zone,
            "dropoffZone": dropoff_zone
        })
        clientSocket.sendto(payload.encode("utf-8"), serverAddress)

    #prints the received message and prompts the user for input
    print(response)
    text = input('YES if you want to proceed: ')
    payload = json.dumps({
        "text": text
    })
    clientSocket.sendto(payload.encode("utf-8"), serverAddress)

