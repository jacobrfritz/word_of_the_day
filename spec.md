Feature Specification: Softmax Temperature Selection1. OverviewCurrently, the word_of_the_day pipeline selects the final word by strictly picking the candidate with the highest cosine similarity score (Argmax). To introduce tunable variance and creativity, this update will replace the strict Argmax selection with a Softmax probability distribution scaled by a configurable temperature parameter.2. Design Philosophy & SOLID PrinciplesTo adhere to good software design, we will use the Strategy Pattern for the selection phase of the pipeline.Single Responsibility Principle (SRP): The logic that scores words (scorers.py) should be entirely separate from the logic that selects the final word based on those scores.Open/Closed Principle (OCP): The pipeline should be open to new selection methods (e.g., Softmax, Top-K, Strict Max) but closed to modification. We achieve this by depending on an abstraction.Dependency Inversion Principle (DIP): pipeline.py will depend on a WordSelector interface rather than a concrete implementation.3. Architecture Changes3.1. Abstraction: WordSelector ProtocolWe will introduce a new abstraction (likely in a new selectors.py file, or as a new module within utils/ or generator.py).from typing import Protocol
from dataclasses import dataclass

@dataclass
class ScoredWord:
    word: str
    score: float

class WordSelector(Protocol):
    def select(self, candidates: list[ScoredWord]) -> str:
        """Selects a single word from a list of scored candidates."""
        ...
3.2. Concrete ImplementationsHighestScoreSelector: Preserves the existing functionality (Argmax). Useful for testing, rollbacks, or specific run configurations.TemperatureSoftmaxSelector: The new implementation requiring a temperature float on initialization.3.3. Application Configuration (config.py & .env.example)Add SELECTION_TEMPERATURE (float) to the application settings.Default value should be 1.0.Add SELECTION_STRATEGY (string, e.g., "softmax" or "argmax") to allow easy toggling.4. Component-Level Implementation GuideA. src/word_of_the_day/config.pyAdd the following fields to your configuration model (likely Pydantic):selection_strategy: str = "softmax"selection_temperature: float = 1.0B. src/word_of_the_day/selectors.py (New File)Implement the Softmax math using numpy for numerical stability (to prevent np.exp() overflow).import numpy as np
# ... (WordSelector Protocol defined here)

class TemperatureSoftmaxSelector:
    def __init__(self, temperature: float = 1.0):
        # Prevent division by zero; clamp to a small positive float
        self.temperature = max(float(temperature), 1e-6)

    def select(self, candidates: list[ScoredWord]) -> str:
        if not candidates:
            raise ValueError("Candidate list cannot be empty")
            
        words = [c.word for c in candidates]
        scores = np.array([c.score for c in candidates], dtype=np.float64)
        
        # Scale by temperature and shift for numerical stability
        scaled_scores = scores / self.temperature
        shifted_scores = scaled_scores - np.max(scaled_scores)
        
        exp_scores = np.exp(shifted_scores)
        probabilities = exp_scores / np.sum(exp_scores)
        
        return np.random.choice(words, p=probabilities)
C. src/word_of_the_day/pipeline.pyRefactor the final selection step. Instead of calling max(words, key=...), inject the configured WordSelector into the pipeline.# Initialization phase based on config
if config.selection_strategy == "softmax":
    selector = TemperatureSoftmaxSelector(temperature=config.selection_temperature)
else:
    selector = HighestScoreSelector()

# ... inside the pipeline run method ...
final_word = selector.select(scored_candidates)
5. Testing RequirementsNew tests should be added to tests/test_selectors.py (or equivalent):Numerical Stability Test: Ensure TemperatureSoftmaxSelector does not raise RuntimeWarning: overflow encountered in exp when given very large or negative scores.Zero/Negative Temperature: Verify the constructor clamps temperature to a small positive number (e.g., 1e-6) to avoid ZeroDivisionError.Probability Distribution Test: Set temperature very high (e.g., 100.0) and assert that the distribution approaches uniform (using a mock np.random.choice).Deterministic Fallback Test: Set temperature very close to 0 and assert it reliably picks the highest score.Integration Test (tests/test_pipeline.py): Ensure the pipeline end-to-end execution succeeds with the new selector injected.6. Rollout PlanImplement configuration updates and .env.example.Implement selectors.py and unit tests.Refactor pipeline.py to use the strategy pattern.Execute full test suite (pytest tests/).Deploy and monitor logs in logger.py for selection distribution anomalies.