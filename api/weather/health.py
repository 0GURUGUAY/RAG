from fastapi import FastAPI


app = FastAPI(title='CEIBO Weather Health', version='1.0.0')


@app.get('/')
def health():
    return {'ok': True, 'service': 'ceibo-weather-analysis'}