from http import client
from socket import *
import json
from datetime import datetime
import threading
import time


global data

#opens and loads the JSON file safely while using a context manager
with open("uberProject.json", "r+", encoding="utf-8") as file:
    data = json.load(file)

def getDistance(zone1, zone2):
    #calculates the distance between two zones based on their coordinates in the JSON data
    zone1_coords = None
    zone2_coords = None

    for zone in data["zones"]:
        if str(zone["zoneId"]) == str(zone1):
            zone1_coords = (zone["zoneLocation"][0], zone["zoneLocation"][1])
        if str(zone["zoneId"]) == str(zone2):
            zone2_coords = (zone["zoneLocation"][0], zone["zoneLocation"][1])

    if zone1_coords is None or zone2_coords is None:
        return None

    distance = ((zone2_coords[0] - zone1_coords[0]) ** 2 + (zone2_coords[1] - zone1_coords[1]) ** 2) ** 0.5
    return distance

#checks if the provided user_id and password match any entry in the JSON data
def passwordCheck(user_id, password):
    user_id = str(user_id).strip()

    for group in ("Customer", "Driver"):
        for person in data.get(group, []):
            if str(person.get("id")) == user_id:
                if person.get("password") == password:
                    return group.lower()
                return "invalid" # ID exist, but wrong password
    return "invalid"

#checks if the provided address matches any entry in the JSON data and returns the corresponding group
def serverCheck(data, address):
    for group in ("Customer", "Driver"):
        for person in data.get(group, []):
            savedAddress = person.get("serverAddress")
            if savedAddress and tuple(savedAddress) == address:
                print(f"Found {group} at address: {address}")
                return group
    print(f"Address {address} not found")
    return "Unknown"

#takes an ID and returns the corresponding server address from the JSON data
def addressFinder(id):
    address = ()
    for group in ("Customer", "Driver"):
        for person in data.get(group, []):
            if str(person.get("id")) == str(id):
                address = person.get("serverAddress")
                break
            else:
                continue
        break
    if address == ():
        print(f"ID {id} not found")
    return tuple(address)

#takes an address and returns the corresponding ID from the JSON data
def idFinder(address):
    for group in ("Customer", "Driver"):
        for person in data.get(group, []):
            if tuple(person.get("serverAddress")) == address:
                return person.get("id")
    return None

#writes the current state of the JSON data back to the file
def writeJSON():
    with open("uberProject.json", "r+", encoding="utf-8") as file:
        file.seek(0)
        json.dump(data, file, indent=2)
        file.truncate()
        file.seek(0)
    return True
    


#sets up the UDP server socket and listens for incoming messages
serverPort = 12000
serverSocket = socket(AF_INET, SOCK_DGRAM)
serverSocket.bind(('', serverPort))
print ('The server is ready to receive')
signedIn = 0
customerAdd = None
driverAdd = None

#main loop that handles incoming messages from clients
while True:
    #sets up the server to receive a message from a client and decodes it from JSON format
    message, clientAddress = serverSocket.recvfrom(2048)
    request = json.loads(message.decode("utf-8"))

    serverChecked = serverCheck(data, clientAddress)

    #if the server address is not recognized, it checks the provided user ID and password against the JSON data
    if serverChecked == "Unknown":
        clientID = str(request["id"])
        clientPass = str(request["password"])

        #loops until a valid user ID and password combination is provided, sending an "Invalid User" message back to the client if the credentials are incorrect
        while True:
            passReturn = passwordCheck(clientID, clientPass)
            if passReturn != "invalid":
                break
            returnMessage = "Invalid User"
            serverSocket.sendto(returnMessage.encode(), clientAddress)

            message, clientAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            clientID = str(request["id"])
            clientPass = str(request["password"])

        #if the credentials are valid, it sends a "passVerified" message back to the client and updates the JSON data with the client's server address
        if passReturn == "customer":
            returnMessage = "passVerified"
            serverSocket.sendto(returnMessage.encode(), clientAddress)
            for customer in data["Customer"]:
                if customer["id"] == clientID:
                    customer["serverAddress"] = list(clientAddress)
                    break
            writeJSON()

        elif passReturn == "driver":
            returnMessage = "passVerified"
            serverSocket.sendto(returnMessage.encode(), clientAddress)
            for driver in data["Driver"]:
                if driver["id"] == clientID:
                    driver["serverAddress"] = list(clientAddress)
                    break
            writeJSON()


    #if the server address is recognized as a driver, it prompts the driver to upload a headshot and view their previous rides, updating the JSON data accordingly.
    #  If the server address is recognized as a customer, it prompts the customer to upload a headshot and view their previous rides, also updating the JSON data accordingly.
    elif serverChecked == "Driver":
        driverMessage = "Would you like to upload a driver headshot?: "
        serverSocket.sendto(driverMessage.encode(), clientAddress)

        #receives the driver's response and decodes it from JSON format
        message, clientAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])

        #if the driver chooses to upload a headshot, it prompts for the headshot and updates the JSON data with the provided information
        if text.lower() == "yes":
            driverMessage = "Please upload your driver headshot."
            serverSocket.sendto(driverMessage.encode(), clientAddress)

            message, clientAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            text = str(request["text"])

            for driver in data["Driver"]:
                if tuple(driver.get("serverAddress", [])) == tuple(clientAddress):
                    driver["headshot"] = list(text)
                    writeJSON()
                    break
            
        #prompts the driver to view their previous rides and updates the JSON data accordingly
        driverMessage = "Would you like to see a list your previous rides?"
        serverSocket.sendto(driverMessage.encode(), clientAddress)

        message, clientAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])
        rides = ""

        #if the driver chooses to view their previous rides, it retrieves the relevant information from the JSON data and sends it back to the driver. 
        # If the driver chooses not to view their previous rides, it prompts them to accept a ride.
        if text.lower() == "yes":
            id = idFinder(tuple(clientAddress))
            for driver in data["rideInfo"]:
                if str(driver["driverId"]) == id:
                    rides += f"Ride ID: {driver['id']}, Customer ID: {driver['customerId']}, Driver ID: {driver['driverId']}, Pickup: {driver['pickupZone']}, Dropoff: {driver['dropoffZone']}, Cost: {driver['cost']}, Request Time: {driver['requestTime']}, Pickup Time: {driver['pickupTime']}, Dropoff Time: {driver['dropoffTime']}\n"

            driverMessage = "Here is a list of your previous rides.\n" + rides + "\nWould you like to request another ride?"
            serverSocket.sendto(driverMessage.encode(), clientAddress)
        else:
            driverMessage = "Would you like to accept a ride?"
            serverSocket.sendto(driverMessage.encode(), clientAddress)

        #receives the driver's response and decodes it from JSON format
        message, clientAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])

        if text.lower() == "yes":
            customerMessage = ""
            serverSocket.sendto(customerMessage.encode(), clientAddress)
        else:
            customerMessage = "kill"
            serverSocket.sendto(customerMessage.encode(), clientAddress)
        




    # if the server address is recognized as a customer, it prompts the customer to upload a headshot and view their previous rides, updating the JSON data accordingly. 
    # If the customer chooses to request another ride, it prompts for the desired pickup zone. 
    elif serverChecked == "Customer":
        customerMessage = "Would you like to upload a customer headshot?: "
        customerAddress = tuple(clientAddress)
        serverSocket.sendto(customerMessage.encode(), customerAddress)

        #receives the customer's response and decodes it from JSON format
        message, customerAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])

        # if the customer chooses to upload a headshot, it prompts for the headshot and updates the JSON data with the provided information
        if text.lower() == "yes":
            customerMessage = "Please upload your headshot."
            serverSocket.sendto(customerMessage.encode(), customerAddress)

            message, customerAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            text = str(request["text"])

            for customer in data["Customer"]:
                if tuple(customer.get("serverAddress", [])) == tuple(customerAddress):
                    customer["headshot"] = text
                    writeJSON()
                    break
            
        #prompts the customer to view their previous rides and updates the JSON data accordingly
        customerMessage = "Would you like to see a list your previous rides?"
        serverSocket.sendto(customerMessage.encode(), customerAddress)

        message, customerAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])
        rides = ""

        #if the customer chooses to view their previous rides, it retrieves the relevant information from the JSON data and sends it back to the customer. If the customer chooses not to view their previous rides, it prompts them to request another ride.
        if text.lower() == "yes":
            id = idFinder(tuple(customerAddress))
            for customer in data["rideInfo"]:
                if str(customer["customerId"]) == id:
                    rides += f"Ride ID: {customer['id']}, Customer ID: {customer['customerId']}, Driver ID: {customer['driverId']}, Pickup: {customer['pickupZone']}, Dropoff: {customer['dropoffZone']}, Cost: {customer['cost']}, Request Time: {customer['requestTime']}, Pickup Time: {customer['pickupTime']}, Dropoff Time: {customer['dropoffTime']}\n"

            customerMessage = "Here is a list of your previous rides.\n" + rides + "\nWould you like to request another ride?"
            serverSocket.sendto(customerMessage.encode(), customerAddress)
        else:
            customerMessage = "Would you like to request another ride?"
            serverSocket.sendto(customerMessage.encode(), customerAddress)

        #receives the customer's response and decodes it from JSON format
        message, customerAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])

        if text.lower() == "yes":
            customerMessage = "What is your desired pickup and dropoff zone? Pickup zone: 1, Dropoff zone: 2"
            serverSocket.sendto(customerMessage.encode(), customerAddress)

            message, customerAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            pickup_zone = str(request["pickupZone"])
            dropoff_zone = str(request["dropoffZone"])

            for customer in data["Customer"]:
                if tuple(customer.get("serverAddress", [])) == tuple(customerAddress):
                    customer["currentZone"] = pickup_zone
                    writeJSON()
                    break

            
            data["rideInfo"][-1]["customerId"] = idFinder(tuple(customerAddress))
            data["rideInfo"][-1]["pickupZone"] = pickup_zone
            data["rideInfo"][-1]["dropoffZone"] = dropoff_zone
            data["rideInfo"][-1]["requestTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data["rideInfo"][-1]["pending"] = 1
            data["rideInfo"][-1]["id"] = len(data["rideInfo"]) + 1
            data["rideInfo"][-1]["cost"] = getDistance(pickup_zone, dropoff_zone) * 5
            writeJSON()

            customerMessage = "Your ride request has been sent to available drivers."
            serverSocket.sendto(customerMessage.encode(), customerAddress)

            while True:
                message, clientAddress = serverSocket.recvfrom(2048)
                request = json.loads(message.decode("utf-8"))

                if serverCheck(data, clientAddress) == "Driver":
                    driver_id = idFinder(tuple(clientAddress))
                    if data["rideInfo"][-1]["pending"] == 1:
                        data["rideInfo"][-1]["driverId"] = driver_id
                        data["rideInfo"][-1]["pending"] = 2
                        writeJSON()
                        for driver in data["Driver"]:
                            if driver["id"] == driver_id:
                                customerMessage = f"Driver {driver_id} has accepted your ride request. headshot: {driver['headshot']}, car model: {driver['model']}, car color: {driver['color']}, plate number: {driver['car']['plateNumber']}"
                                break

                        serverSocket.sendto(customerMessage.encode(), customerAddress)
                        driverMessage = f"Ride request accepted. Customer ID: {data['rideInfo'][-1]['customerId']}, Pickup Zone: {pickup_zone}, Dropoff Zone: {dropoff_zone}, Cost: {data['rideInfo'][-1]['cost']}"
                        serverSocket.sendto(driverMessage.encode(), clientAddress)
                        break
            customerMessage = "kill"
            serverSocket.sendto(customerMessage.encode(), customerAddress)               

        else:
            customerMessage = "kill"
            serverSocket.sendto(customerMessage.encode(), customerAddress)
