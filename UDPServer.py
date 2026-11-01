from http import client
from socket import *
import json
from datetime import datetime
import threading
import queue
import time

clientQueue = {}
queueLock = threading.Lock()
dataLock = threading.Lock()

global data

#opens and loads the JSON file safely while using a context manager
with open("uberProject.json", "r+", encoding="utf-8") as file:
    data = json.load(file)

def recieveFor(address):
    #waits for the next packet routed to this client
    packet = clientQueue[address].get()
    return json.loads(packet.decode("utf-8"))

def sendTo(address, message):
    serverSocket.sendto(message.encode("utf-8"), address)

def handleClient(clientAddress, firstPacket):
    try:
        request = json.loads(firstPacket.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as error:
        print(f"Invalid Packet from {clientAddress}: {error}")
    finally:
        with queueLock:
            clientQueue.pop(clientAddress, None)



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
        print(f"Received message from unknown address: {clientAddress}")
        clientID = str(request["id"])
        clientPass = str(request["password"])

        #loops until a valid user ID and password combination is provided, sending an "Invalid User" message back to the client if the credentials are incorrect
        while True:
            passReturn = passwordCheck(clientID, clientPass)
            if passReturn != "invalid":
                break
            returnMessage = "Invalid User"

            print(f"Invalid login attempt from address: {clientAddress} with ID: {clientID}")
            serverSocket.sendto(returnMessage.encode(), clientAddress)

            message, clientAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            clientID = str(request["id"])
            clientPass = str(request["password"])
            print(f"Received message from {clientAddress} with ID: {clientID}")

        #if the credentials are valid, it sends a "passVerified" message back to the client and updates the JSON data with the client's server address
        if passReturn == "customer":
            returnMessage = "passVerified"
            print(f"Verified login for customer ID: {clientID} from address: {clientAddress}")
            serverSocket.sendto(returnMessage.encode(), clientAddress)
            for customer in data["Customer"]:
                if customer["id"] == clientID:
                    customer["serverAddress"] = list(clientAddress)
                    break
            writeJSON()

        elif passReturn == "driver":
            returnMessage = "passVerified"
            print(f"Verified login for driver ID: {clientID} from address: {clientAddress}")
            serverSocket.sendto(returnMessage.encode(), clientAddress)
            for driver in data["Driver"]:
                if driver["id"] == clientID:
                    driver["serverAddress"] = list(clientAddress)
                    break
            writeJSON()


    #if the server address is recognized as a driver, it prompts the driver to upload a headshot and view their previous rides, updating the JSON data accordingly.
    #  If the server address is recognized as a customer, it prompts the customer to upload a headshot and view their previous rides, also updating the JSON data accordingly.
    elif serverChecked == "Driver":
        print(f"Received message from Driver address: {clientAddress}")
        driverID = idFinder(tuple(clientAddress))
        driverMessage = "Would you like to upload a driver headshot?: "
        driverAddress = tuple(clientAddress)
        serverSocket.sendto(driverMessage.encode(), driverAddress)
        print(f"Driver ID: {driverID} at address: {driverAddress}. Asking about headshot upload.")

        #receives the driver's response and decodes it from JSON format
        message, driverAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])
        print(f"Driver ID: {driverID} at address: {driverAddress} responded with: {text}")


        #if the driver chooses to upload a headshot, it prompts for the headshot and updates the JSON data with the provided information
        if text.lower() == "yes":
            driverMessage = "Please upload your driver headshot."
            serverSocket.sendto(driverMessage.encode(), driverAddress)
            print(f"Driver ID: {driverID} at address: {driverAddress}. Sent request for headshot upload.")

            message, driverAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            text = str(request["text"])
            print(f"Driver ID: {driverID} at address: {driverAddress} responded to headshot request with: {text}")

            for driver in data["Driver"]:
                if driverID == driver["id"]:
                    driver["headshot"] = list(text)
                    writeJSON()
                    break
            
        #prompts the driver to view their previous rides and updates the JSON data accordingly
        driverMessage = "Would you like to see a list your previous rides?"
        serverSocket.sendto(driverMessage.encode(), driverAddress)
        print(f"Driver ID: {driverID} at address: {driverAddress}. Asking about previous rides.")

        message, driverAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])
        print(f"Driver ID: {driverID} at address: {driverAddress} responded with: {text}")
        rides = ""
        print(f"Driver ID: {driverID} at address: {driverAddress}. Responded with: {text}")


        #if the driver chooses to view their previous rides, it retrieves the relevant information from the JSON data and sends it back to the driver. 
        # If the driver chooses not to view their previous rides, it prompts them to accept a ride.
        if text.lower() == "yes":
            for driver in data["rideInfo"]:
                if str(driver["driverId"]) == driverID:
                    rides += f"\nRide ID: {driver['id']}, \nCustomer ID: {driver['customerId']}, \nDriver ID: {driver['driverId']}, \nPickup: {driver['pickupZone']}, \nDropoff: {driver['dropoffZone']}, \nCost: {driver['cost']}, \nRequest Time: {driver['requestTime']}, \nPickup Time: {driver['pickupTime']}, \nDropoff Time: {driver['dropoffTime']}\n"

            driverMessage = "Here is a list of your previous rides.\n" + rides + "\nWould you like to request another ride?"
            serverSocket.sendto(driverMessage.encode(), driverAddress)
        else:
            driverMessage = "Would you like to accept a ride?"
            serverSocket.sendto(driverMessage.encode(), driverAddress)

        #receives the driver's response and decodes it from JSON format
        message, driverAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])
        print(f"Driver ID: {driverID} at address: {driverAddress} responded with: {text}")


        #Based on the driver's response, it either prompts for the current zone and enters 
        # a loop to continuously check for pending ride requests, assigning the first 
        # available ride to the driver and updating the JSON data accordingly, or it sends 
        # a "kill" message to terminate the interaction.
        if text.lower() == "yes":
            driverMessage = "What is your current zone? (1, 2, ..., 9)"
            serverSocket.sendto(driverMessage.encode(), driverAddress)
            print(f"Driver ID: {driverID} at address: {driverAddress}. Asked for current zone.")


            #receives the driver's response and decodes it from JSON format
            message, driverAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            text = str(request["text"])
            print(f"Driver ID: {driverID} at address: {driverAddress} responded with current zone: {text}")


            for driver in data["Driver"]:
                if driverID == driver["id"]:
                    driver["currentZone"] = text
                    driverCurrentZone = text
                    writeJSON()
                    break
            
            #enters a loop to continuously check for pending ride requests and assigns the first available ride to the driver, updating the JSON data accordingly.
            print("Waiting for a ride request...")
            rideFound = False
            while not rideFound:
                for ride in data["rideInfo"]:
                    if ride["pending"] == 1:
                        ride["pending"] = 2
                        ride["driverId"] = driverID
                        writeJSON()
                        rideFound = True
                        break

            print("Ride request found. Sending ride details to driver...")
            message, driverAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            text = str(request["text"])
            print(f"Driver ID: {driverID} at address: {driverAddress} responded with: {text}")
            
            for ride in data["rideInfo"]:
                if ride["driverId"] == driverID and ride["pending"] == 2:
                    customerID = ride["customerId"]
                    customerAddress = addressFinder(customerID)
                    print(f"Driver {driverID} is heading to pickup zone {ride['pickupZone']} for customer {ride['customerId']}.")
                    while ride["pickupZone"] != driverCurrentZone:
                        if driverCurrentZone < ride["pickupZone"]:
                            driverCurrentZone = int(driverCurrentZone) + 1
                            time.sleep(2)
                        elif driverCurrentZone > ride["pickupZone"]:
                            driverCurrentZone = int(driverCurrentZone) - 1
                            time.sleep(2)
                        else:
                            break
                    print(f"Driver {driverID} has arrived at pickup zone {ride['pickupZone']} for customer {ride['customerId']}.")
                    ride["pickupTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ride["pending"] = 3
                    writeJSON()
                    time.sleep(3)

                    print(f"Driver {driverID} is heading to dropoff zone {ride['dropoffZone']} with customer {ride['customerId']}.")
                    while ride["dropoffZone"] != driverCurrentZone:
                        if driverCurrentZone < ride["dropoffZone"]:
                            driverCurrentZone = int(driverCurrentZone) + 1
                            time.sleep(2)
                        elif driverCurrentZone > ride["dropoffZone"]:
                            driverCurrentZone = int(driverCurrentZone) - 1
                            time.sleep(2)
                        else:
                            break
                    
                    print(f"Driver {driverID} has arrived at dropoff zone {ride['dropoffZone']} with customer {ride['customerId']}.")
                    ride["dropoffTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ride["pending"] = 4
                    writeJSON()
                    break

            for driver in data["Driver"]:
                if driver["id"] == driverID:
                        driver["available"] = True
                        break
            for customer in data["Customer"]:
                if customer["id"] == customerID:
                    customer["riding"] = False
                    break
            writeJSON()

            driverMessage = "kill"
            serverSocket.sendto(driverMessage.encode(), driverAddress)
        else:
            driverMessage = "kill"
            serverSocket.sendto(driverMessage.encode(), driverAddress)
        





    # if the server address is recognized as a customer, it prompts the customer to upload a headshot and view their previous rides, updating the JSON data accordingly. 
    # If the customer chooses to request another ride, it prompts for the desired pickup zone. 
    elif serverChecked == "Customer":
        print(f"Received message from Customer address: {clientAddress}")
        customerMessage = "Would you like to upload a customer headshot?: "
        customerAddress = tuple(clientAddress)
        customerID = idFinder(tuple(customerAddress))
        serverSocket.sendto(customerMessage.encode(), customerAddress)
        print(f"Customer ID: {customerID} at address: {customerAddress}. Asking about headshot upload.")

        #receives the customer's response and decodes it from JSON format
        message, customerAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])
        print(f"Customer ID: {customerID} at address: {customerAddress} responsed with: {text}")


        # if the customer chooses to upload a headshot, it prompts for the headshot and updates the JSON data with the provided information
        if text.lower() == "yes":
            customerMessage = "Please upload your headshot."
            serverSocket.sendto(customerMessage.encode(), customerAddress)
            print(f"Customer ID: {customerID} at address: {customerAddress}. Sent request for headshot upload.")

            message, customerAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            text = str(request["text"])
            print(f"Customer ID: {customerID} at address: {customerAddress}. Headshot: {text}")

            for customer in data["Customer"]:
                if tuple(customer.get("serverAddress", [])) == tuple(customerAddress):
                    customer["headshot"] = text
                    writeJSON()
                    break
            
        #prompts the customer to view their previous rides and updates the JSON data accordingly
        customerMessage = "Would you like to see a list your previous rides?"
        serverSocket.sendto(customerMessage.encode(), customerAddress)
        print(f"Customer ID: {customerID} at address: {customerAddress}. Asking about previous rides.")

        message, customerAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])
        rides = ""
        print(f"Customer ID: {customerID} at address: {customerAddress}. Responded with: {text}")


        #if the customer chooses to view their previous rides, it retrieves the relevant information from the 
        # JSON data and sends it back to the customer. If the customer chooses not to view their previous
        #  rides, it prompts them to request another ride.
        if text.lower() == "yes":
            for customer in data["rideInfo"]:
                if str(customer["customerId"]) == customerID:
                    rides += f"\nRide ID: {customer['id']}, \nCustomer ID: {customer['customerId']}, \nDriver ID: {customer['driverId']}, \nPickup: {customer['pickupZone']}, \nDropoff: {customer['dropoffZone']}, \nCost: {customer['cost']}, \nRequest Time: {customer['requestTime']}, \nPickup Time: {customer['pickupTime']}, \nDropoff Time: {customer['dropoffTime']}\n"

            customerMessage = "Here is a list of your previous rides.\n" + rides + "\nWould you like to request another ride?"
            serverSocket.sendto(customerMessage.encode(), customerAddress)
            print(f"Customer ID: {customerID} at address: {customerAddress}. Sent previous rides and asked about requesting another ride.")
        else:
            customerMessage = "Would you like to request another ride?"
            serverSocket.sendto(customerMessage.encode(), customerAddress)
            print(f"Customer ID: {customerID} at address: {customerAddress}. Asked about requesting another ride.")

        #receives the customer's response and decodes it from JSON format
        message, customerAddress = serverSocket.recvfrom(2048)
        request = json.loads(message.decode("utf-8"))
        text = str(request["text"])
        print(f"Customer ID: {customerID} at address: {customerAddress}. Responded with: {text}")


        #Based on the customer's response, it either prompts for the desired pickup and dropoff zones and 
        # updates the JSON data with the ride request information, or it sends a "kill" message to 
        # terminate the interaction.
        if text.lower() == "yes":
            customerMessage = "What is your desired pickup and dropoff zone? Pickup zone: 1, Dropoff zone: 2"
            serverSocket.sendto(customerMessage.encode(), customerAddress)
            print(f"Customer ID: {customerID} at address: {customerAddress}. Asked for pickup and dropoff zones.")

            message, customerAddress = serverSocket.recvfrom(2048)
            request = json.loads(message.decode("utf-8"))
            pickup_zone = str(request["pickupZone"])
            dropoff_zone = str(request["dropoffZone"])

            print(f"Customer ID: {customerID} at address: {customerAddress}. Pickup zone: {pickup_zone}, Dropoff zone: {dropoff_zone}")

            for customer in data["Customer"]:
                if tuple(customer.get("serverAddress", [])) == tuple(customerAddress):
                    customer["currentZone"] = pickup_zone
                    writeJSON()
                    break

            #Collects the customer's ID, pickup zone, dropoff zone, request time, and calculates the
            # cost of the ride based on the distance between the pickup and dropoff zones.
            # It then updates the JSON data with this information and sends a message to the customer 
            # confirming that their ride request has been sent to available drivers. The server then
            #  enters a loop to wait for a response from a driver, and if a driver accepts the ride request, 
            # it updates the JSON data
            data["rideInfo"][-1]["customerId"] = customerID
            data["rideInfo"][-1]["pickupZone"] = pickup_zone
            data["rideInfo"][-1]["dropoffZone"] = dropoff_zone
            data["rideInfo"][-1]["requestTime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data["rideInfo"][-1]["pending"] = 1
            data["rideInfo"][-1]["id"] = len(data["rideInfo"]) + 1
            data["rideInfo"][-1]["cost"] = getDistance(pickup_zone, dropoff_zone) * 5
            writeJSON()

            customerMessage = "Your ride request has been sent to available drivers."
            serverSocket.sendto(customerMessage.encode(), customerAddress)
            driverFound = False
            print("Waiting for a driver to accept the ride request...")

            while not driverFound:
                for ride in data["rideInfo"]:
                    time.sleep(1)
                    if ride["pending"] == 2:
                        driverFound = True
                        ride_id = ride["id"]
                        driver_id = ride["driverId"]
                        break

                
            for driver in data["Driver"]:
                if driver["id"] == driver_id:
                    customerMessage = f"\nRide {ride_id} inicitated\nDriver {driver_id} has accepted your ride request. \nheadshot: {driver['headshot']}, \nCar model: {driver['model']}, \nCar color: {driver['color']}, \nPlate number: {driver['car']['plateNumber']}"
                    driver["available"] = False
                    break
            for customer in data["Customer"]:
                if customer["id"] == customerID:
                    customer["riding"] = True
                    break
            writeJSON()

            serverSocket.sendto(customerMessage.encode(), customerAddress)
            driverMessage = f"Ride request accepted. \nCustomer ID: {data['rideInfo'][-1]['customerId']}, \nPickup Zone: {pickup_zone}, \nDropoff Zone: {dropoff_zone}, \nCost: {data['rideInfo'][-1]['cost']}"
            for driver in data["Driver"]:
                if driver["id"] == driver_id:
                    driverAddress = tuple(driver.get("serverAddress", []))
                    break
            
            print(f"Sent ride request details.")
            serverSocket.sendto(driverMessage.encode(), driverAddress)

            customerMessage = "kill"
            serverSocket.sendto(customerMessage.encode(), customerAddress)               

        else:
            customerMessage = "kill"
            serverSocket.sendto(customerMessage.encode(), customerAddress)
