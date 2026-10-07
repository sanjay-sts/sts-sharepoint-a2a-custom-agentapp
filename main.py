from dotenv import load_dotenv
import os


def load_env():
    load_dotenv()


def main():
    print("Hello from sts-sharepoint-a2a-custom-agentapp!")
    print(os.environ.get("CLIENTID"))
    print(os.environ.get("TENANTID"))


if __name__ == "__main__":
    load_env()
    main()
