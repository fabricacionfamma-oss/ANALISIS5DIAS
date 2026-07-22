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
                   e.Interval as [Tiempo (Min)], t1.Name as Categoria_Macro, t2.Name as Detalle_Final,
                   e.Date as Fecha_Filtro
            FROM EVENT_01 e
            LEFT JOIN CELL c ON e.CellId = c.CellId
            LEFT JOIN EVENTTYPE t1 ON e.EventTypeLevel1 = t1.EventTypeId
            LEFT JOIN EVENTTYPE t2 ON e.EventTypeLevel2 = t2.EventTypeId
            WHERE e.Date BETWEEN '{ini_str}' AND '{fin_str}'
        """
        df_eventos = conn.query(q_event)

        if not df_eventos.empty:
            df_eventos['Tiempo (Min)'] = pd.to_numeric(df_eventos['Tiempo (Min)'], errors='coerce').fillna(0)
            df_eventos['Categoria_Macro'] = df_eventos['Categoria_Macro'].fillna('No Asignado')
            df_eventos['Fecha'] = pd.to_datetime(df_eventos['Fecha_Filtro']).dt.date
            
            def categorizar(row):
                texto = str(row['Categoria_Macro']).upper() + " " + str(row['Detalle_Final']).upper()
                if 'PRODUCCION' in texto or 'PRODUCCIÓN' in texto: return 'Producción'
                if 'BAÑO' in texto or 'REFRIGERIO' in texto: return 'Descanso'
                if 'PARADA' in texto: return 'Parada Programada'
                return 'Falla/Gestión'
            
            df_eventos['Estado_Global'] = df_eventos.apply(categorizar, axis=1)

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

if df_metrics['OEE'].max() > 1.5:  
    for col in ['OEE', 'PERFORMANCE', 'DISPONIBILIDAD', 'CALIDAD']:
        df_metrics[col] = df_metrics[col] / 100.0

# ==========================================
# 4. FUNCIÓN RENDERIZADORA DE ÁREAS (SCROLL CONTINUO)
# ==========================================
def render_area_dashboard(area_name, grupos_area, df_m, df_e, df_p, df_h):
    # Filtrar datos exclusivos de esta área
    df_m_area = df_m[df_m['Grupo'].isin(grupos_area)].copy()
    df_e_area = df_e[df_e['Grupo'].isin(grupos_area)].copy() if not df_e.empty else pd.DataFrame()
    df_p_area = df_p[df_p['Grupo'].isin(grupos_area)].copy() if not df_p.empty else pd.DataFrame()
    df_h_area = df_h[df_h['Grupo'].isin(grupos_area)].copy() if not df_h.empty else pd.DataFrame()

    if df_m_area.empty:
        st.info(f"No hay datos registrados para el área de {area_name} en este periodo.")
        return

    # --- SECCIÓN 1: KPIs ---
    st.markdown(f"### 📈 Indicadores Generales - {area_name}")
    t_operativo_tot = df_m_area['T_Operativo'].sum()
    t_planificado_tot = df_m_area['T_Operativo'].sum() + df_m_area['T_Parada'].sum()
    
    perf_global = (df_m_area['PERFORMANCE'] * df_m_area['T_Operativo']).sum() / t_operativo_tot if t_operativo_tot else 0
    disp_global = (df_m_area['DISPONIBILIDAD'] * t_planificado_tot).sum() / t_planificado_tot if t_planificado_tot else 0
    cal_global = df_m_area['CALIDAD'].mean() 
    
    c1, c2, c3 = st.columns(3)
    c1.metric("PERFORMANCE", f"{perf_global*100:.1f}%")
    c2.metric("DISPONIBILIDAD", f"{disp_global*100:.1f}%")
    c3.metric("CALIDAD", f"{cal_global*100:.1f}%")
    
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
            
            fallas_grp['% DE LAS FALLAS'] = (fallas_grp['Tiempo (Min)'] / total_fallas_min)
            fallas_grp['% DOWN TIME'] = (fallas_grp['Tiempo (Min)'] / total_downtime_area)
            
            fallas_grp = fallas_grp.rename(columns={'Categoria_Macro': 'CATEGORÍA', 'Tiempo (Min)': 'TIEMPO (MIN)'})
            
            col_chart1, col_chart2 = st.columns([1.2, 1])
            with col_chart1:
                st.dataframe(
                    fallas_grp,
                    column_config={
                        "CATEGORÍA": st.column_config.TextColumn("CATEGORÍA"),
                        "TIEMPO (MIN)": st.column_config.NumberColumn("TIEMPO (MIN)", format="%.2f"),
                        "% DE LAS FALLAS": st.column_config.NumberColumn("% DE LAS FALLAS", format="%.1f %%"),
                        "% DOWN TIME": st.column_config.NumberColumn("% DOWN TIME", format="%.1f %%"),
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
    
    st.dataframe(
        df_maq_show,
        column_config={
            "OEE": st.column_config.ProgressColumn("OEE", format="%.1f %%", min_value=0, max_value=1),
            "DISPONIBILIDAD": st.column_config.NumberColumn("Disponibilidad", format="%.1f %%"),
            "PERFORMANCE": st.column_config.NumberColumn("Performance", format="%.1f %%"),
            "CALIDAD": st.column_config.NumberColumn("Calidad", format="%.1f %%"),
        },
        hide_index=True,
        use_container_width=True
    )
    
    st.divider()

    # --- SECCIÓN 4: HORARIOS Y PRODUCCIÓN DIARIA ---
    st.markdown(f"### 🕒 Horarios de Producción - {area_name}")
    
    col_h1, col_h2 = st.columns(2)
    with col_h1:
        st.markdown("**Tabla de Horarios**")
        if not df_h_area.empty:
            df_h_show = df_h_area[['Dia', 'Turno', 'Máquina', 'Hora_Inicio', 'Hora_Cierre', 'Apertura_Neta_Min']].copy()
            df_h_show['Dia'] = pd.to_datetime(df_h_show['Dia']).dt.strftime('%d/%m/%Y')
            st.dataframe(df_h_show.sort_values(by=['Dia', 'Turno']), hide_index=True, use_container_width=True)
        else:
            st.info("No hay horarios.")
            
    with col_h2:
        st.markdown("**Producción por Día (Eventos)**")
        if not df_e_area.empty:
            prod_resumen = df_e_area[df_e_area['Estado_Global']=='Producción'].groupby('Fecha')['Tiempo (Min)'].sum().reset_index()
            st.dataframe(prod_resumen, hide_index=True, use_container_width=True)
        else:
            st.info("No hay eventos de producción.")

# ==========================================
# 5. PESTAÑAS PRINCIPALES (SOLO PARA ÁREAS)
# ==========================================
tab_estampado, tab_soldadura = st.tabs(["🏭 ESTAMPADO", "🔥 SOLDADURA"])

with tab_estampado:
    render_area_dashboard("ESTAMPADO", GRUPOS_ESTAMPADO, df_metrics, df_eventos, df_prod, df_horarios)

with tab_soldadura:
    render_area_dashboard("SOLDADURA", GRUPOS_SOLDADURA, df_metrics, df_eventos, df_prod, df_horarios)
