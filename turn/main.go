package main

import (
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"strconv"
	"syscall"

	"github.com/pion/turn/v4"
)

func main() {
	publicIP := flag.String("public-ip", "", "Public IP of this server (required for clients to reach the relay)")
	port := flag.Int("port", 3478, "TURN listening port")
	realmFlag := flag.String("realm", "coopnet", "TURN realm")
	userFlag := flag.String("user", "coopnet", "Username for long-term credentials")
	passFlag := flag.String("pass", "coopnetpass", "Password for long-term credentials")
	flag.Parse()

	if *publicIP == "" {
		// Try to guess public IP (not always accurate)
		fmt.Println("WARNING: --public-ip not set. Clients may not be able to use the relay correctly.")
		fmt.Println("         Example: ./turnserver --public-ip 203.0.113.10")
	}

	// Create UDP listener
	udpListener, err := net.ListenPacket("udp4", "0.0.0.0:"+strconv.Itoa(*port))
	if err != nil {
		log.Fatalf("Failed to create UDP listener: %v", err)
	}
	defer udpListener.Close()

	fmt.Printf("TURN server listening on UDP 0.0.0.0:%d\n", *port)
	if *publicIP != "" {
		fmt.Printf("Public IP announced: %s\n", *publicIP)
	}
	fmt.Printf("Credentials → user: %s  |  pass: %s  |  realm: %s\n", *userFlag, *passFlag, *realmFlag)

	// Auth handler (long-term credentials)
	expectedUser := *userFlag
	expectedPass := *passFlag
	expectedRealm := *realmFlag

	authHandler := func(username string, realm string, srcAddr net.Addr) ([]byte, bool) {
		if username == expectedUser {
			return turn.GenerateAuthKey(username, realm, expectedPass), true
		}
		return nil, false
	}

	// Relay address generator
	var relayGen turn.RelayAddressGenerator
	if *publicIP != "" {
		relayGen = &turn.RelayAddressGeneratorStatic{
			RelayAddress: net.ParseIP(*publicIP),
			Address:      "0.0.0.0",
		}
	} else {
		relayGen = &turn.RelayAddressGeneratorNone{}
	}

	server, err := turn.NewServer(turn.ServerConfig{
		Realm:       expectedRealm,
		AuthHandler: authHandler,
		PacketConnConfigs: []turn.PacketConnConfig{
			{
				PacketConn:            udpListener,
				RelayAddressGenerator: relayGen,
			},
		},
	})
	if err != nil {
		log.Fatalf("Failed to create TURN server: %v", err)
	}

	// Graceful shutdown
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
	<-sigs

	fmt.Println("\nShutting down TURN server...")
	if err := server.Close(); err != nil {
		log.Printf("Error closing server: %v", err)
	}
}
