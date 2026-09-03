#!/usr/bin/env python3
import os
import sys
import json
import argparse
import urllib.request
import urllib.error

def load_env(env_path):
    """Carga variables de entorno desde un archivo .env."""
    if not os.path.exists(env_path):
        return

    # Intentar importar dotenv para parsear, o caer al parseo manual
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
        return
    except ImportError:
        pass

    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ[key] = val

def main():
    parser = argparse.ArgumentParser(description="Check if Ollama is working and listening on OpenAI-compatible endpoints.")
    parser.add_argument(
        '-p', '--prompt',
        type=str,
        help="Optional test prompt. If provided, checks chat completions endpoint."
    )
    args = parser.parse_args()

    # Cargar la configuración del entorno
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(script_dir, '.env')
    load_env(env_path)

    ollama_host = os.environ.get('OLLAMA_HOST', 'http://localhost:11434').rstrip('/')
    ollama_model = os.environ.get('OLLAMA_MODEL', 'llama3')

    print("Checking Ollama configuration...")
    print(f"Ollama Host:  {ollama_host}")
    print(f"Ollama Model: {ollama_model}")
    print("-" * 50)

    # 1. Chequeo de conexión vía /v1/models
    models_url = f"{ollama_host}/v1/models"
    print(f"Checking connection and retrieving models via: {models_url}...")
    try:
        req = urllib.request.Request(models_url, method='GET')
        with urllib.request.urlopen(req, timeout=5) as response:
            status = response.status
            body = response.read().decode('utf-8')
            
        if status == 200:
            print("\033[92m[SUCCESS]\033[0m Successfully connected to Ollama OpenAI-compatible endpoint.")
            try:
                data = json.loads(body)
                models = [m.get('id') for m in data.get('data', [])]
                print(f"Available OpenAI-compatible models: {', '.join(models) if models else 'None'}")
            except Exception as e:
                print(f"[WARNING] Connected, but failed to parse response JSON: {e}")
        else:
            print(f"\033[91m[FAILURE]\033[0m Received unexpected status code: {status}")
            sys.exit(1)
            
    except urllib.error.URLError as e:
        print(f"\033[91m[FAILURE]\033[0m Connection to Ollama failed. Error: {e.reason}")
        print("Please verify that Ollama is running and OLLAMA_HOST is correctly set in the .env file.")
        sys.exit(1)
    except Exception as e:
        print(f"\033[91m[FAILURE]\033[0m An unexpected error occurred: {e}")
        sys.exit(1)

    # 2. Chequeo opcional de chat completions
    if args.prompt:
        print("-" * 50)
        completions_url = f"{ollama_host}/v1/chat/completions"
        print(f"Testing chat completions with model '{ollama_model}'...")
        print(f"Prompt: \"{args.prompt}\"")
        
        payload = {
            "model": ollama_model,
            "messages": [
                {"role": "user", "content": args.prompt}
            ],
            "temperature": 0.7
        }
        
        headers = {
            "Content-Type": "application/json"
        }
        
        data_bytes = json.dumps(payload).encode('utf-8')
        
        try:
            req = urllib.request.Request(completions_url, data=data_bytes, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=30) as response:
                status = response.status
                body = response.read().decode('utf-8')
                
            if status == 200:
                resp_json = json.loads(body)
                choices = resp_json.get('choices', [])
                if choices:
                    content = choices[0].get('message', {}).get('content', '')
                    print("\033[92m[SUCCESS]\033[0m Chat completions endpoint responded successfully.")
                    print("\nResponse:")
                    print(content.strip())
                else:
                    print("\033[93m[WARNING]\033[0m Responded, but structure is missing 'choices'.")
                    print(f"Response body: {body}")
            else:
                print(f"\033[91m[FAILURE]\033[0m Chat completion request failed with status: {status}")
                sys.exit(1)
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ""
            print(f"\033[91m[FAILURE]\033[0m HTTP Error occurred during chat completion: {e.code} {e.reason}")
            if error_body:
                print(f"Response: {error_body}")
            sys.exit(1)
        except urllib.error.URLError as e:
            print(f"\033[91m[FAILURE]\033[0m Connection during chat completion failed. Error: {e.reason}")
            sys.exit(1)
        except Exception as e:
            print(f"\033[91m[FAILURE]\033[0m An unexpected error occurred: {e}")
            sys.exit(1)

if __name__ == '__main__':
    main()
