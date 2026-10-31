from socket import *
serverName = 'localhost'
serverPort = 12000
clientSocket = socket(AF_INET, SOCK_DGRAM)

login = 0

while login == 0:
    message = input('Input username:')
    message += input('Input password:')
    clientSocket.sendto(message.encode(),(serverName, serverPort))
    response, serverAddress = clientSocket.recvfrom(2048)
    response = response.decode()
    if response == "passVerified":
        login = 1
    else:
        print("Login Failed")

print ("Login Successful")

response, serverAddress = clientSocket.recvfrom(2048)
response = response.decode()

print(response)

