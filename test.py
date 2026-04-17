from google import genai

# Hardcode it just for this test to bypass the .env file completely
MY_KEY = AQ.Ab8RN6IPisVeXzlZg9ZlD_Pkxc-HclIsDrIqTcHUbPuSugGJcg

print("Attempting to contact Gemini...")

try:
    client = genai.Client(AQ.Ab8RN6IPisVeXzlZg9ZlD_Pkxc-HclIsDrIqTcHUbPuSugGJcg=MY_KEY)
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents='Respond with exactly one word: Hello.'
    )
    print("\nSUCCESS! Gemini says:", response.text)
except Exception as e:
    print("\nFAILED! Google rejected the request. Error details:")
    print(e)