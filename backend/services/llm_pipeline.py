import os
import json 
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def extracted_uml_entities_from_chunks(chunks: list[str]) -> dict:
    """
    Sends the chunked text to openai llm(gpt-4o-mini ti extract uml entities
    Forces the output to be in a strict JSON format/structure
    """

    if not chunks:
        return {"classes": [], "relationships":[]}
    
    #process the chunks by combining them, Assuming the sliding windows chunks easily fit into the 128K token limit of gpt-4o-mini


    combined_text = "\n\n--- Next Section ---\n\n".join(chunks)

    system_prompt = """
    You are an expert Software Architect and Requirements Engineer.
    Your task is to read the provided software requirements specification and extract Object-Oriented UML entities.
    
    You MUST output strictly in JSON format matching this exact schema:
    {
      "classes": [
        {
          "class_name": "String (PascalCase)",
          "is_abstract": "boolean",
          "attributes": [
            {"name": "String (camelCase)", "data_type": "String", "visibility": "public|private|protected"}
          ],
          "methods": [
            {"name": "String (camelCase)", "return_type": "String", "visibility": "public|private|protected"}
          ]
        }
      ],
      "relationships": [
        {
          "source_class": "String",
          "target_class": "String",
          "relationship_type": "Association|Aggregation|Composition|Inheritance",
          "multiplicity_source": "String (e.g., '1', '0..*')",
          "multiplicity_target": "String"
        }
      ]
    }
    Only extract entities explicitly mentioned or strongly implied by the text. Do not hallucinate standard features if they are not requested.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Extract UML entities from the following text:\n\n{combined_text}"}
            ])
        
        # Parse string JSON returned by the model into a dictionary
        extracted_data = json.loads(response.choices[0].message.content)
        return extracted_data
    
    except Exception as ex:
        print(f"Error during LLM processing: {ex}")
        return {"classes": [], "relationships": []}
