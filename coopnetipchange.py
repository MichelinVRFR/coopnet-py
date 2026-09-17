import os
import shutil

# Automatically uses the current Windows user's AppData\Roaming folder
CONFIG_PATH = os.path.join(
    os.environ["APPDATA"],
    "sm64coopdx",
    "sm64config.txt"
)

DEFAULT_DOMAIN = "net.coop64.us"


def change_ip(ip_address):
    if not os.path.exists(CONFIG_PATH):
        print("\nERROR: sm64config.txt was not found!")
        print(f"Expected location:\n{CONFIG_PATH}")
        input("\nPress Enter to continue...")
        return

    # Create a backup before changing the config
    backup_path = CONFIG_PATH + ".backup"

    try:
        shutil.copy2(CONFIG_PATH, backup_path)

        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            content = file.read()

        lines = content.splitlines()
        found = False
        new_lines = []

        for line in lines:
            if line.strip().startswith("coopnet_ip "):
                new_lines.append(f"coopnet_ip {ip_address}")
                found = True
            else:
                new_lines.append(line)

        # Add the setting if it does not already exist
        if not found:
            new_lines.append(f"coopnet_ip {ip_address}")

        with open(CONFIG_PATH, "w", encoding="utf-8") as file:
            file.write("\n".join(new_lines) + "\n")

        print(f"\nCoopNet IP changed to: {ip_address}")
        print(f"Backup created at:\n{backup_path}")

    except Exception as e:
        print("\nERROR: Could not modify the config file.")
        print(e)

    input("\nPress Enter to continue...")


def main():
    while True:
        os.system("cls")

        print("====================================")
        print("  Super Mario 64 Coop DX")
        print("     CoopNet IP Changer")
        print("====================================")
        print()
        print("1. Custom IP/Domain")
        print("2. Default Domain (net.coop64.us)")
        print("3. Exit")
        print()

        choice = input("Select an option: ").strip()

        if choice == "1":
            print()
            ip = input("Enter IP address or domain: ").strip()

            if ip:
                change_ip(ip)
            else:
                print("No IP/domain entered.")
                input("\nPress Enter to continue...")

        elif choice == "2":
            change_ip(DEFAULT_DOMAIN)

        elif choice == "3":
            print("\nGoodbye!")
            break

        else:
            print("\nInvalid option.")
            input("Press Enter to continue...")


if __name__ == "__main__":
    main()
