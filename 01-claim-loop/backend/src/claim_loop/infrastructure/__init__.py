"""Adapters to the outside world: database, model providers, delivery.

Everything replaceable lives here. Swapping the stub extractor for a real vision
model, or the CLI for FastAPI, touches only this layer.
"""
