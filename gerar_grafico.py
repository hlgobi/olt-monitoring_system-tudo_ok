import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import numpy as np

# Configurações do gráfico
fig, ax = plt.subplots(figsize=(16, 10))
fig.suptitle('Timeline de Execução por Ciclo - Coleta de Dados OLT', fontsize=16, fontweight='bold')

# Dados das tarefas (nome, início, duração, cor)
tasks = [
    # Fase de Conexão
    ("Conexão SSH", 0, 10, '#4CAF50'),
    ("Modo Enable", 10, 2, '#8BC34A'),
    
    # Fase de Descoberta
    ("Placas Ativas", 12, 5, '#CDDC39'),
    
    # Fase de Portas PON (Paralelo)
    ("Tráfego PON", 17, 10, '#FFEB3B'),
    ("Estado Porta", 22, 8, '#FFC107'),
    ("Estatísticas PON", 27, 7, '#FF9800'),
    ("Tráfego ONTs", 32, 15, '#FF5722'),
    
    # Fase de ONTs
    ("Detalhes ONT", 47, 12, '#795548'),
    ("Estatísticas ONT", 55, 12, '#9E9E9E'),
    
    # Fase Ethernet
    ("Portas ETH", 62, 15, '#607D8B'),
    
    # Finalização
    ("Desconexão", 77, 3, '#3F51B5'),
    
    # Espera
    ("Espera Próximo Ciclo", 80, 60, '#E91E63')
]

# Criar barras horizontais
y_pos = np.arange(len(tasks))
for i, (task, start, duration, color) in enumerate(tasks):
    ax.barh(y_pos[i], duration, left=start, height=0.6, color=color, alpha=0.8, edgecolor='black')
    
    # Adicionar texto na barra
    ax.text(start + duration/2, i, f"{duration}s", 
            ha='center', va='center', color='white', fontweight='bold')

# Configurar eixo Y
ax.set_yticks(y_pos)
ax.set_yticklabels([task[0] for task in tasks])
ax.invert_yaxis()  # Inverter para mostrar na ordem correta

# Configurar eixo X
ax.set_xlim(0, 140)
ax.set_xlabel('Tempo (segundos)', fontsize=12)
ax.set_xticks(np.arange(0, 141, 10))
ax.set_xticklabels([f"{i}s" for i in range(0, 141, 10)])

# Adicionar grade
ax.grid(True, which='both', linestyle='--', alpha=0.5)

# Adicionar linha vertical a cada 10 segundos
for i in range(0, 141, 10):
    ax.axvline(x=i, color='gray', linestyle=':', alpha=0.3)

# Destacar fases com retângulos
phase_patches = [
    {"xy": (0, 8.5), "width": 12, "height": 2, "color": "green", "alpha": 0.1, "label": "Conexão"},
    {"xy": (12, 8.5), "width": 5, "height": 1, "color": "yellow", "alpha": 0.1, "label": "Descoberta"},
    {"xy": (17, 4.5), "width": 30, "height": 4, "color": "orange", "alpha": 0.1, "label": "Portas PON"},
    {"xy": (47, 2.5), "width": 20, "height": 2, "color": "brown", "alpha": 0.1, "label": "ONTs"},
    {"xy": (62, 1.5), "width": 15, "height": 1, "color": "blue", "alpha": 0.1, "label": "Ethernet"},
    {"xy": (77, 0.5), "width": 3, "height": 1, "color": "purple", "alpha": 0.1, "label": "Finalização"},
    {"xy": (80, -0.5), "width": 60, "height": 1, "color": "pink", "alpha": 0.1, "label": "Espera"}
]

for patch in phase_patches:
    rect = plt.Rectangle((patch["xy"][0], patch["xy"][1]), patch["width"], patch["height"],
                        color=patch["color"], alpha=patch["alpha"])
    ax.add_patch(rect)

# Adicionar legenda
legend_elements = [plt.Rectangle((0,0),1,1, facecolor=patch["color"], alpha=patch["alpha"], 
                                edgecolor='black', label=patch["label"]) 
                  for patch in phase_patches]
ax.legend(handles=legend_elements, loc='upper right', bbox_to_anchor=(1.15, 1))

# Ajustar layout
plt.tight_layout()
plt.subplots_adjust(right=0.85)

# Salvar como PNG
plt.savefig('timeline_execucao_olt.png', dpi=300, bbox_inches='tight')
print("Gráfico salvo como 'timeline_execucao_olt.png'")

# Mostrar o gráfico (opcional)
plt.show()