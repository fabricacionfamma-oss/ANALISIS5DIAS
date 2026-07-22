import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import timedelta

# ==========================================
# 0. CONFIGURACIÓN Y ESTILOS
# ==========================================
st.set_page_config(page_title="Dashboard Producción - FAMMA", layout="wide", page_icon="📊")

st.markdown("""
<style>
    .metric-container { background-color: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 5px solid #3498db; }
    .header-style { font-size: 28px; font-weight: bold; color: #2C3E50; margin-bottom: 0px; }
    .subheader-style { font-size: 16px; color: #7F8C8D; margin-bottom: 20px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. DICCIONARIO DE MÁQUINAS Y GRUPOS
# ==========================================
MAQUINAS_MAP = {
    "GENERAL": "LÍNEAS ESTAMPADO" 
}
GRUPOS_ESTAMPADO = ['LÍNEAS ESTAMPADO']
GRUPOS_SOLDADURA = ['CELDAS SOLDADURA', 'EQUIPOS PRP']

def asignar_grupo_dinamico(maq):
    maq_u = str(maq).strip().upper()
    if maq_u in MAQUINAS_MAP: return MAQUINAS_MAP[maq_u]
    if 'CELL' in maq_u or 'CELDA' in maq_u: return 'CELDAS SOLDADURA'
    if 'LINEA' in maq_u or 'LÍNEA' in maq_u: return 'LÍNEAS ESTAMPADO'
    if 'PRP' in maq_u or 'SOLD' in maq_u: return 'EQUIPOS PRP'
    return 'Otro'

# ==========================================
# 2. CARGA DE DATOS DESDE SQL SERVER
# ==========================================
@st.cache_data(ttl=300)
def fetch_data_from_db(fecha_ini, fecha_fin):
    try:
        conn = st.connection("wii_bi", type="sql")
        ini_str = fecha_ini.strftime('%Y-%m-%d')
        fin_str = fecha_fin.strftime('%Y-%m-%d')

        q_prod = f"""
            SELECT c.Name as Máquina, pr.Code as Código, 
                   SUM(p.Good) as Buenas, SUM(p.Rework) as Retrabajo, SUM(p.Scrap) as Observadas
            FROM PROD_D_01 p JOIN CELL c ON p.CellId = c.CellId JOIN PRODUCT pr ON p.ProductId = pr.ProductId 
            WHERE p.Date BETWEEN '{ini_str}' AND '{fin_str}' GROUP BY c.Name, pr.Code
        """
        df_prod = conn.query(q_prod)

        q_metrics = f"""
            SELECT c.Name as Máquina, 
                   SUM(p.Good) as Buenas, SUM(p.Rework) as Retrabajo, SUM(p.Scrap) as Observadas,
                   SUM(p.ProductiveTime) as T_Operativo, SUM(p.DownTime) as T_Parada,
                   (SUM(p.Performance * p.ProductiveTime) / NULLIF(SUM(p.ProductiveTime), 0)) as PERFORMANCE,
                   (SUM(p.Availability * (p.ProductiveTime + p.DownTime)) / NULLIF(SUM(p.ProductiveTime + p.DownTime), 0)) as DISPONIBILIDAD,
                   (SUM(p.Quality * (p.Good + p.Rework + p.Scrap)) / NULLIF(SUM(p.Good + p.Rework + p.Scrap), 0)) as CALIDAD,
                   (SUM(p.Oee * (p.ProductiveTime + p.DownTime)) / NULLIF(SUM(p.ProductiveTime + p.DownTime), 0)) as OEE
            FROM PROD_D_03 p JOIN CELL c ON p.CellId = c.CellId
            WHERE p.Date BETWEEN '{ini_str}' AND '{fin_str}'
            GROUP BY c.Name
        """
        df_metrics = conn.query(q_metrics)

        q_horarios = f"""
            WITH Tiempos_Turno AS (
                SELECT CellId, TurnId, Date as Dia, MIN(Started) as MinInicio, MAX(Finish) as MaxFin
                FROM EVENT_01
                WHERE Date BETWEEN '{ini_str}' AND '{fin_str}'
                GROUP BY CellId, TurnId, Date
            )
            SELECT c.Name as Máquina, tu.Name as Turno, t.Dia,
                   FORMAT(MIN(t.MinInicio), 'HH:mm') as Hora_Inicio,
                   FORMAT(MAX(t.MaxFin), 'HH:mm') as Hora_Cierre,
                   SUM(ISNULL(p.ProductiveTime, 0) + ISNULL(p.DownTime, 0)) as Apertura_Neta_Min
            FROM Tiempos_Turno t
            JOIN CELL c ON t.CellId = c.CellId JOIN TURN tu ON t.TurnId = tu.TurnId
            LEFT JOIN PROD_D_02 p ON t.CellId = p.CellId AND t.TurnId = p.TurnId AND t.Dia = p.Date
            GROUP BY c.Name, tu.Name, t.Dia
        """
        df_horarios = conn.query(q_horarios)

        q_event = f"""
            SELECT e.Id as Evento_Id, c.Name as Máquina, e.Started as Inicio, e.Finish as Fin, 
                   e.Interval as [Tiempo (Min)], 
                   t1.Name as [Nivel Evento 1], t2.Name as [Nivel Evento 2], 
                   t3.Name as [Nivel Evento 3], t4.Name as [Nivel Evento 4], 
                   t5.Name as [Nivel Evento 5], t6.Name as [Nivel Evento 6],
                   t7.Name as [Nivel Evento 7], t8.Name as [Nivel Evento 8],
                   t9.Name as [Nivel Evento 9],
                   e.Date as Fecha_Filtro
            FROM EVENT_01 e
            LEFT JOIN CELL c ON e.CellId = c.CellId
            LEFT JOIN EVENTTYPE t1 ON e.EventTypeLevel1 = t1.EventTypeId
            LEFT JOIN EVENTTYPE t2 ON e.EventTypeLevel2 = t2.EventTypeId
            LEFT JOIN EVENTTYPE t3 ON e.EventTypeLevel3 = t3.EventTypeId
            LEFT JOIN EVENTTYPE t4 ON e.EventTypeLevel4 = t4.EventTypeId
            LEFT JOIN EVENTTYPE t5 ON e.EventTypeLevel5 = t5.EventTypeId
            LEFT JOIN EVENTTYPE t6 ON e.EventTypeLevel6 = t6.EventTypeId
            LEFT JOIN EVENTTYPE t7 ON e.EventTypeLevel7 = t7.EventTypeId
            LEFT JOIN EVENTTYPE t8 ON e.EventTypeLevel8 = t8.EventTypeId
            LEFT JOIN EVENTTYPE t9 ON e.EventTypeLevel9 = t9.EventTypeId
            WHERE e.Date BETWEEN '{ini_str}' AND '{fin_str}'
        """
        df_eventos = conn.query(q_event)

        if not df_eventos.empty:
            df_eventos['Tiempo (Min)'] = pd.to_numeric(df_eventos['Tiempo (Min)'], errors='coerce').fillna(0)
            df_eventos['Fecha'] = pd.to_datetime(df_eventos['Fecha_Filtro']).dt.date
            df_eventos['Hora_Inicio'] = pd.to_datetime(df_eventos['Inicio']).dt.strftime('%H:%M')
            df_eventos['Hora_Fin'] = pd.to_datetime(df_eventos['Fin']).dt.strftime('%H:%M')
            
            cols_niveles = [c for c in df_eventos.columns if 'Nivel Evento' in c]

            def categorizar_estado(row):
                texto_completo = " ".join([str(row.get(c, '')) for c in cols_niveles]).upper()
                if 'PRODUCCION' in texto_completo or 'PRODUCCIÓN' in texto_completo: return 'Producción'
                if 'PROYECTO' in texto_completo: return 'Proyecto'
                if 'BAÑO' in texto_completo or 'BANO' in texto_completo or 'REFRIGERIO' in texto_completo: return 'Descanso'
                if 'PARADA PROGRAMADA' in texto_completo: return 'Parada Programada'
                return 'Falla/Gestión'

            def clasificar_macro(row):
                texto_completo = " ".join([str(row.get(c, '')) for c in cols_niveles]).upper()
                categorias_clave = ["MANTENIMIENTO", "MATRICERIA", "DISPOSITIVOS", "TECNOLOGIA", "GESTION", "LOGISTICA", "CALIDAD"]
                for cat in categorias_clave:
                    if cat in texto_completo:
                        return cat.capitalize()
                return 'Otra Falla/Gestión'

            def obtener_detalle_final(row):
                niveles = [str(row.get(c, '')) for c in cols_niveles]
                validos = [n.strip() for n in niveles if n.strip() and n.strip().lower() not in ['none', 'nan', 'null']]
                if not validos: return "Sin detalle en sistema"
                ultimo_dato = validos[-1].upper()
                estado = row.get('Estado_Global', '')
                categoria = row.get('Categoria_Macro', '')
                if estado == 'Falla/Gestión':
                    if categoria != 'Otra Falla/Gestión':
                        return f"[{categoria.upper()}] {ultimo_dato}"
                    return ultimo_dato
                return validos[-1]

            df_eventos['Estado_Global'] = df_eventos.apply(categorizar_estado, axis=1)
            df_eventos['Categoria_Macro'] = df_eventos.apply(clasificar_macro, axis=1)
            df_eventos['Detalle_Final'] = df_eventos.apply(obtener_detalle_final, axis=1)

        return df_prod, df_metrics, df_horarios, df_eventos

    except Exception as e:
        st.error(f"Error ejecutando consulta a base de datos: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ==========================================
# 3. INTERFAZ: CABECERA Y FILTROS
# ==========================================
col_title, col_btn = st.columns([4, 1])
with col_title:
    st.markdown('<p class="header-style">Dashboard de Producción Bi-Semanal</p>', unsafe_allow_html=True)
    st.markdown('<p class="subheader-style">Visión consolidada de los últimos 5 días de operación.</p>', unsafe_allow_html=True)
with col_btn:
    if st.button("🔄 Actualizar Datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.divider()

hoy = pd.to_datetime("today").date()
default_ini = hoy - timedelta(days=5)

col1, col2 = st.columns(2)
with col1:
    fecha_ini = st.date_input("Fecha Inicio", value=default_ini)
with col2:
    fecha_fin = st.date_input("Fecha Fin", value=hoy)

# Cargar Datos
df_prod, df_metrics, df_horarios, df_eventos = fetch_data_from_db(fecha_ini, fecha_fin)

if df_metrics.empty:
    st.warning("No hay datos disponibles para el rango de fechas seleccionado.")
    st.stop()

# Aplicar grupo a todos los DataFrames
for df in [df_metrics, df_prod, df_horarios, df_eventos]:
    if not df.empty and 'Máquina' in df.columns:
        df['Grupo'] = df['Máquina'].apply(asignar_grupo_dinamico)

# Estandarizar base métrica a rango [0, 1] internamente para hacer bien los cálculos
if df_metrics['OEE'].max() > 1.5:  
    for col in ['OEE', 'PERFORMANCE', 'DISPONIBILIDAD', 'CALIDAD']:
        df_metrics[col] = df_metrics[col] / 100.0

# ==========================================
# 4. FUNCIÓN RENDERIZADORA DE ÁREAS
# ==========================================
def render_area_dashboard(area_name, grupos_area, df_m, df_e, df_p, df_h):
    df_m_area = df_m[df_m['Grupo'].isin(grupos_area)].copy()
    df_e_area = df_e[df_e['Grupo'].isin(grupos_area)].copy() if not df_e.empty else pd.DataFrame()
    df_p_area = df_p[df_p['Grupo'].isin(grupos_area)].copy() if not df_p.empty else pd.DataFrame()
    df_h_area = df_h[df_h['Grupo'].isin(grupos_area)].copy() if not df_h.empty else pd.DataFrame()

    if df_m_area.empty:
        st.info(f"No hay datos registrados para el área de {area_name} en este periodo.")
        return

    maquinas_activas = sorted(df_m_area['Máquina'].unique().tolist())
    maquinas_str = ", ".join(maquinas_activas)

    # --- SECCIÓN 1: KPIs ---
    st.markdown(f"### 📈 Indicadores Generales - {area_name}")
    st.caption(f"**Máquinas Operativas en el periodo:** {maquinas_str}")
    
    df_m_area['T_Planificado'] = df_m_area['T_Operativo'].fillna(0) + df_m_area['T_Parada'].fillna(0)
    df_m_area['Piezas_Totales'] = df_m_area['Buenas'].fillna(0) + df_m_area['Retrabajo'].fillna(0) + df_m_area['Observadas'].fillna(0)
    
    t_operativo_tot = df_m_area['T_Operativo'].sum()
    t_planificado_tot = df_m_area['T_Planificado'].sum()
    piezas_tot = df_m_area['Piezas_Totales'].sum()
    
    perf_global = (df_m_area['PERFORMANCE'] * df_m_area['T_Operativo']).sum() / t_operativo_tot if t_operativo_tot > 0 else 0
    disp_global = (df_m_area['DISPONIBILIDAD'] * df_m_area['T_Planificado']).sum() / t_planificado_tot if t_planificado_tot > 0 else 0
    cal_global = (df_m_area['CALIDAD'] * df_m_area['Piezas_Totales']).sum() / piezas_tot if piezas_tot > 0 else 0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("PERFORMANCE", f"{perf_global*100:.2f}%")
    c2.metric("DISPONIBILIDAD", f"{disp_global*100:.2f}%")
    c3.metric("CALIDAD", f"{cal_global*100:.2f}%")
    
    st.divider()

    # --- SECCIÓN 2: ANÁLISIS DE FALLOS ---
    st.markdown(f"### ⚠️ Resumen de Fallos Acumulados - {area_name}")
    
    if not df_e_area.empty:
        df_fallas = df_e_area[df_e_area['Estado_Global'] == 'Falla/Gestión'].copy()
        
        if not df_fallas.empty:
            fallas_grp = df_fallas.groupby('Categoria_Macro')['Tiempo (Min)'].sum().reset_index()
            total_fallas_min = fallas_grp['Tiempo (Min)'].sum()
            total_downtime_area = df_m_area['T_Parada'].sum() 
            
            if total_downtime_area == 0: total_downtime_area = total_fallas_min
            
            fallas_grp['% DE LAS FALLAS'] = (fallas_grp['Tiempo (Min)'] / total_fallas_min) * 100
            fallas_grp['% DOWN TIME'] = (fallas_grp['Tiempo (Min)'] / total_downtime_area) * 100
            
            fallas_grp = fallas_grp.rename(columns={'Categoria_Macro': 'CATEGORÍA', 'Tiempo (Min)': 'TIEMPO (MIN)'})
            
            col_chart1, col_chart2 = st.columns([1.2, 1])
            with col_chart1:
                st.dataframe(
                    fallas_grp,
                    column_config={
                        "CATEGORÍA": st.column_config.TextColumn("CATEGORÍA"),
                        "TIEMPO (MIN)": st.column_config.NumberColumn("TIEMPO (MIN)", format="%.2f"),
                        "% DE LAS FALLAS": st.column_config.NumberColumn("% DE LAS FALLAS", format="%.2f %%"),
                        "% DOWN TIME": st.column_config.NumberColumn("% DOWN TIME", format="%.2f %%"),
                    },
                    hide_index=True,
                    use_container_width=True
                )
            with col_chart2:
                fig_fallas_pie = px.pie(fallas_grp, values='TIEMPO (MIN)', names='CATEGORÍA', hole=0.4)
                fig_fallas_pie.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=250)
                st.plotly_chart(fig_fallas_pie, use_container_width=True)
        else:
            st.success("No se registraron fallas en este período.")
    else:
        st.info("No hay eventos registrados.")

    st.divider()

    # --- SECCIÓN 3: DESGLOSE POR MÁQUINA ---
    st.markdown(f"### 🏭 Desempeño Individual por Máquina - {area_name}")
    
    df_maq_show = df_m_area[['Máquina', 'OEE', 'DISPONIBILIDAD', 'PERFORMANCE', 'CALIDAD']].copy()
    df_maq_show['OEE'] = df_maq_show['OEE'] * 100
    df_maq_show['DISPONIBILIDAD'] = df_maq_show['DISPONIBILIDAD'] * 100
    df_maq_show['PERFORMANCE'] = df_maq_show['PERFORMANCE'] * 100
    df_maq_show['CALIDAD'] = df_maq_show['CALIDAD'] * 100
    
    st.dataframe(
        df_maq_show,
        column_config={
            "Máquina": st.column_config.TextColumn("Máquina", width="medium"),
            "OEE": st.column_config.ProgressColumn("OEE", format="%.2f %%", min_value=0, max_value=100),
            "DISPONIBILIDAD": st.column_config.NumberColumn("Disponibilidad", format="%.2f %%"),
            "PERFORMANCE": st.column_config.NumberColumn("Performance", format="%.2f %%"),
            "CALIDAD": st.column_config.NumberColumn("Calidad", format="%.2f %%"),
        },
        hide_index=True,
        use_container_width=True
    )
    
    st.divider()

    # --- SECCIÓN 4: HORARIOS DE PRODUCCIÓN ---
    st.markdown(f"### 🕒 Horarios de Producción - {area_name}")
    
    col_h1, col_h2 = st.columns(2)
    with col_h1:
        st.markdown("**Tabla de Horarios por Máquina**")
        if not df_h_area.empty:
            df_h_grouped = df_h_area.groupby(['Dia', 'Máquina']).agg(
                Hora_Inicio=('Hora_Inicio', 'min'),
                Hora_Cierre=('Hora_Cierre', 'max'),
                Apertura_Neta_Min=('Apertura_Neta_Min', 'sum')
            ).reset_index()
            
            df_h_grouped['Dia'] = pd.to_datetime(df_h_grouped['Dia']).dt.strftime('%d/%m/%Y')
            
            st.dataframe(
                df_h_grouped.sort_values(by=['Dia', 'Máquina']), 
                column_config={
                    "Dia": "Fecha",
                    "Máquina": "Máquina",
                    "Hora_Inicio": "Apertura",
                    "Hora_Cierre": "Cierre",
                    "Apertura_Neta_Min": st.column_config.NumberColumn("Apertura Neta (Min)", format="%.1f")
                },
                hide_index=True, 
                use_container_width=True
            )
        else:
            st.info("No hay horarios registrados en este periodo.")
            
    with col_h2:
        st.markdown("**Producción por Día y Máquina (Eventos)**")
        if not df_e_area.empty:
            df_prod_eventos = df_e_area[df_e_area['Estado_Global'] == 'Producción'].copy()
            
            if not df_prod_eventos.empty:
                prod_resumen = df_prod_eventos.groupby(['Fecha', 'Máquina']).agg(
                    Cantidad_Eventos=('Evento_Id', 'count'),
                    Tiempo_Min=('Tiempo (Min)', 'sum')
                ).reset_index()
                
                prod_resumen['Horas_Totales'] = prod_resumen['Tiempo_Min'] / 60.0
                prod_resumen['Fecha'] = pd.to_datetime(prod_resumen['Fecha']).dt.strftime('%d/%m/%Y')
                
                st.dataframe(
                    prod_resumen.sort_values(by=['Fecha', 'Máquina']), 
                    column_config={
                        "Fecha": "Fecha",
                        "Máquina": "Máquina",
                        "Cantidad_Eventos": st.column_config.NumberColumn("Cant. Eventos"),
                        "Tiempo_Min": st.column_config.NumberColumn("Tiempo (Min)", format="%.1f"),
                        "Horas_Totales": st.column_config.NumberColumn("Horas Totales", format="%.2f hs")
                    },
                    hide_index=True, 
                    use_container_width=True
                )
            else:
                st.info("No hay eventos de producción en los días seleccionados.")
        else:
            st.info("No hay eventos registrados.")

    st.divider()

    # --- SECCIÓN 5: CRONOLOGÍA DE EVENTOS POR MÁQUINA Y DÍA ---
    st.markdown(f"### 📋 Cronología de Eventos - {area_name}")
    st.caption("Despliega cada máquina y día para ver en detalle sus registros ordenados cronológicamente.")
    
    if not df_e_area.empty:
        df_e_area = df_e_area.sort_values(by=['Máquina', 'Fecha', 'Inicio'])
        maquinas_ev = sorted(df_e_area['Máquina'].unique())
        
        for maq in maquinas_ev:
            df_maq_ev = df_e_area[df_e_area['Máquina'] == maq]
            fechas_maq = df_maq_ev['Fecha'].unique()
            
            for fecha in fechas_maq:
                df_maq_dia_ev = df_maq_ev[df_maq_ev['Fecha'] == fecha]
                fecha_str = pd.to_datetime(fecha).strftime('%d/%m/%Y')
                
                with st.expander(f"⚙️ Registros de {maq} - {fecha_str} ({len(df_maq_dia_ev)} eventos)"):
                    df_show = df_maq_dia_ev[['Hora_Inicio', 'Hora_Fin', 'Estado_Global', 'Detalle_Final', 'Tiempo (Min)']].copy()
                    
                    st.dataframe(
                        df_show,
                        column_config={
                            "Hora_Inicio": "Inicio",
                            "Hora_Fin": "Fin",
                            "Estado_Global": "Tipo de Evento",
                            "Detalle_Final": st.column_config.TextColumn("Descripción Detallada (Último Nivel)", width="large"),
                            "Tiempo (Min)": st.column_config.NumberColumn("Duración (Min)", format="%.1f")
                        },
                        hide_index=True,
                        use_container_width=True
                    )
    else:
        st.info("No hay eventos registrados para mostrar en el cronograma.")

# ==========================================
# 6. PESTAÑAS PRINCIPALES (SOLO PARA ÁREAS)
# ==========================================
tab_estampado, tab_soldadura = st.tabs(["🏭 ESTAMPADO", "🔥 SOLDADURA"])

with tab_estampado:
    render_area_dashboard("ESTAMPADO", GRUPOS_ESTAMPADO, df_metrics, df_eventos, df_prod, df_horarios)

with tab_soldadura:
    render_area_dashboard("SOLDADURA", GRUPOS_SOLDADURA, df_metrics, df_eventos, df_prod, df_horarios)

# ==========================================
# 7. PLANES DE ACCIÓN (GOOGLE SHEETS HTML IFRAME)
# ==========================================
st.divider()
st.markdown("### 📝 Registro de Planes de Acción")
st.caption("Añade y revisa los planes de acción para los indicadores, máquinas o eventos que se encuentren fuera de objetivo.")

URL_GOOGLE_SHEET = "https://docs.google.com/spreadsheets/d/1SoNRJjE4Kg2x_bRgylMRQs70JO-2wLOFQtUlBjx1-EA/edit?rm=minimal#gid=0"

# Usar HTML puro evita que la página salte hacia arriba al hacer clic
html_iframe = f"""
    <iframe 
        src="{URL_GOOGLE_SHEET}" 
        width="100%" 
        height="650px" 
        frameborder="0" 
        scrolling="yes" 
        style="border: 1px solid #ccc; border-radius: 8px;">
    </iframe>
"""

st.markdown(html_iframe, unsafe_allow_html=True)

st.markdown(f'<a href="{URL_GOOGLE_SHEET}" target="_blank" style="text-decoration: none;"><button style="margin-top: 10px; padding: 8px 15px; border-radius: 5px; background-color: #3498db; color: white; border: none; cursor: pointer;">Abrir en pestaña completa ↗️</button></a>', unsafe_allow_html=True)
