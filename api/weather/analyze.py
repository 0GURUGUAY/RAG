import requests
from fastapi import FastAPI, HTTPException

from weather.server import WeatherAnalyzeRequest, run_analysis


app = FastAPI(title='CEIBO Weather Analyze', version='1.0.0')


@app.post('/api/weather/analyze')
def analyze(payload: WeatherAnalyzeRequest):
    try:
        return run_analysis(payload.lat, payload.lon, payload.horizon_days, payload.language)
    except HTTPException:
        raise
    except requests.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f'API meteo distante en erreur: {exc}') from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Analyse meteo impossible: {exc}') from exc