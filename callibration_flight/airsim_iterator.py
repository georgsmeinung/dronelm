import subprocess
import sys
import os
import argparse
from datetime import datetime

# Cantidad de iteraciones por defecto
NUM_ITERATIONS = 10


def parse_arguments():
    """Parsea los argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Run airsim_commander.py multiple times for flight simulation recreation."
    )
    parser.add_argument(
        "--path-file",
        required=True,
        help="Path to the file that contains the mission commands to pass to airsim_commander.py.",
    )
    parser.add_argument(
        "iterations",
        nargs="?",
        type=int,
        default=NUM_ITERATIONS,
        help=f"Number of times to run airsim_commander.py (default: {NUM_ITERATIONS})"
    )
    args = parser.parse_args()
    
    # Validar la entrada
    if args.iterations <= 0:
        print(f"Error: Number of iterations must be positive. Got: {args.iterations}")
        sys.exit(1)
    
    return args


def run_iteration(iteration_num, script_path, path_file):
    """
    Corre una sola iteración de airsim_commander.py.

    Args:
        iteration_num: número de iteración actual (empieza en 1)
        script_path: ruta a airsim_commander.py
        path_file: ruta al archivo de comandos de misión que se le pasa a airsim_commander.py

    Returns:
        Tupla (success: bool, error_msg: str o None)
    """
    try:
        print(f"\n{'='*60}")
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting iteration {iteration_num}")
        print(f"{'='*60}")
        
        # Correr el script commander
        result = subprocess.run(
            [sys.executable, script_path, "--path-file", path_file],
            cwd=os.path.dirname(script_path),
            capture_output=False,
            timeout=None
        )
        
        if result.returncode == 0:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iteration {iteration_num} completed successfully.")
            return True, None
        else:
            error_msg = f"Iteration {iteration_num} exited with return code {result.returncode}"
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {error_msg}")
            return False, error_msg
    
    except subprocess.TimeoutExpired:
        error_msg = f"Iteration {iteration_num} timed out"
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error: {error_msg}")
        return False, error_msg
    
    except Exception as e:
        error_msg = f"Iteration {iteration_num} failed with exception: {str(e)}"
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error: {error_msg}")
        return False, error_msg

def main():
    """Función principal para correr múltiples iteraciones de airsim_commander.py."""
    # Parsear argumentos
    args = parse_arguments()
    
    print(f"Starting airsim_iterator with {args.iterations} iteration(s)")
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Obtener la ruta a airsim_commander.py
    script_dir = os.path.dirname(os.path.abspath(__file__))
    commander_path = os.path.join(script_dir, "airsim_commander.py")
    
    if not os.path.exists(commander_path):
        print(f"Error: {commander_path} not found.")
        sys.exit(1)
    
    # Correr las iteraciones
    results = []
    for i in range(1, args.iterations + 1):
        success, error_msg = run_iteration(i, commander_path, args.path_file)
        results.append((i, success, error_msg))
    
    # Reporte resumen
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Total iterations: {args.iterations}")
    
    successful = sum(1 for _, success, _ in results if success)
    failed = sum(1 for _, success, _ in results if not success)
    
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    
    if failed > 0:
        print("\nFailed iterations:")
        for iter_num, success, error_msg in results:
            if not success:
                print(f"  - Iteration {iter_num}: {error_msg}")
    
    print(f"\nEnd time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    # Salir con el código correspondiente
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
