"""
Script to transform the seq2seq outputs to tempeval format that can be used by the tempeval script
"""
import os
import re
from argparse import ArgumentParser
from typing import List

import numpy as np
import torch
from bs4 import BeautifulSoup
from tqdm import tqdm
from transformers import BertTokenizerFast, RobertaTokenizerFast, EncoderDecoderModel


def get_args():
    args = ArgumentParser()
    args.add_argument("--input_dir", type=str, default="./data/temporal/tempeval/tempeval_test",
                      help="Folder containing the files to be processed")
    args.add_argument("--output_dir", type=str,
                      default="./results/seq2seq/tempeval/fine_tune_mixed/tempeval_test_seq2seq_roberta_67",
                      help="Defines the output directory for the files.")
    args.add_argument("--file_ext", type=str, default="tml",
                      help="File extensions of processed files will have to match this value.")
    args.add_argument("--model_type", type=str, default="roberta",
                      help="type of the evaluated model")
    args.add_argument("--dataset_type", default="tempeval", choices=["tempeval", "tweets", "wikiwars"],
                      help="The dataset type we are looking at.")
    args.add_argument("--model_path", type=str,
                      default="./fine_tune/roberta2roberta_fine_tuned_no_prefix/roberta2roberta_fine_tune_no_prefixed_seed_67",
                      help="path to the model")
    args.add_argument("--max_length", type=int, default=512,
                      help="max input len")
    args.add_argument("--min_length", type=int, default=56,
                      help="max input len")
    args.add_argument("--early_stopping", type=bool, default=True,
                      help="stop beam search when num_beams sentences are finished per batch.")
    args.add_argument("--length_penalty", type=int, default=2,
                      help="Set to values < 1.0 in order to encourage the model to generate shorter sequences, to a value > 1.0 in order to encourage the model to produce longer sequences.")
    args.add_argument("--num_beams", type=int, default=2,
                      help="numbers of beams for beam search")
    args.add_argument("--no_repeat_ngram_size", type=int, default=3,
                      help="n-grams of this size can occur once")

    return args.parse_args()


def process_file(in_fp, data_type):
    """
    Process a single file
    :param in_fp: path to the file
    :param data_type: file type
    :return:
    """
    text, annotations, date = get_text_and_annotations_and_date(in_fp)  # get all the annotations.

    new_text = ""
    first_beginning = 0
    for annotation in annotations:
        begin, end, type, value = annotation
        new_text = new_text + text[first_beginning:begin]
        new_text = new_text + f' <timex3 type="{type}" value="{value}">{text[begin:end]}</timex3> '
        first_beginning = end

    new_text = new_text + text[first_beginning:]
    new_data_tag = []
    for tag in new_text.split("\n"):
        if len(tag) > 0:
            new_data_tag.append(tag)

    new_data = []
    for txt in text.split("\n"):
        if len(txt) > 0:
            new_data.append(txt)

    with open(in_fp) as f:
        all_line = "\n".join(f.readlines())
    if data_type != "tweets":
        id_start = all_line.find("<TEXT>")
        beginning_text = all_line[:id_start] + "<TEXT>"
        end_text = "\n\n</TEXT>\n</TimeML>"
    else:
        id_start = all_line.find("<TEXT>")
        beginning_text = all_line[:id_start] + "<TEXT>"
        end_text = "\n</TEXT>\n</TimeML>"

    return new_data, new_data_tag, beginning_text, end_text, text


def get_text_and_annotations_and_date(in_fp) -> (str, List[str], str):
    soup = BeautifulSoup(open(in_fp), "lxml")

    date = soup.findAll("dct")[0].findAll("timex3")[0].attrs["value"]
    content = soup.findAll("text")[0]
    annotations = []
    end = 0  # Only look in the "remaining string", by saving the previous end position

    for timex in content.findAll("timex3"):
        begin = content.text[end:].index(timex.text) + end
        end = begin + len(timex.text)
        try:
            value = timex.attrs["value"]

        except:
            value = "null"
        annotations.append((begin, end, timex.attrs["type"], value))

    text = content.text
    return text, annotations, date


def clean_predictions(decoded_preds):
    """
    clean the seq2seq predictions
    :param decoded_preds: the raw predictionss
    :return: cleaned text
    """

    # take care of tag formatting
    decoded_preds = decoded_preds.replace("&gt;", ">").replace("&lt;", "<")
    decoded_preds = decoded_preds.replace(" < / timex3  ", " </timex3") \
        .replace("< timex3 ", "<timex3 ") \
        .replace("< / timex3 >", "</timex3>") \
        .replace("/ timex3 >", "</timex3>") \
        .replace(" </timex>", " </timex3>") \
        .replace("</timex3></timex3>", "</timex3>") \
        .replace("timex&gt;", "</timex3>") \
        .replace("timex ", "</timex3> ").replace("</time x3>","</timex3>")
    decoded_preds = re.sub(r"([a-z])timex3>", "\g<1> </timex3>", decoded_preds)
    decoded_preds = re.sub(r"</timex3></timex3>", "</timex3>", decoded_preds)
    decoded_preds = re.sub(r"timex>", "</timex3>", decoded_preds)
    decoded_preds = re.sub(r" </ </timex3>", "</timex3>", decoded_preds)

    # remove the most prominent hallucinations.
    decoded_preds = decoded_preds.replace('type="D"', 'type="DATE"')
    decoded_preds = decoded_preds.replace('type="DATEATION"', 'type="DATE"')
    decoded_preds = decoded_preds.replace('type="DUR"', 'type="DATE"')
    decoded_preds = decoded_preds.replace('type="S"', 'type="SET"')
    decoded_preds = decoded_preds.replace('type="S"', 'type="SET"')
    decoded_preds = decoded_preds.replace('type="TIMEATE"', 'type="TIME"')
    decoded_preds = decoded_preds.replace('type="TIMEATEATION"', 'type="TIME"')
    decoded_preds = decoded_preds.replace('type="TIMEURATION"', 'type="TIME"')
    decoded_preds = decoded_preds.replace('value="PENT_REF"', 'value="PRESENT_REF"')
    decoded_preds = decoded_preds.replace('value="PRESXD"', 'value="PRESENT_REF"')
    decoded_preds = decoded_preds.replace('value="PRESENTD"', 'value="PRESENT_REF"')
    decoded_preds = decoded_preds.replace('type="SETURY"', 'type="SET"')
    decoded_preds = decoded_preds.replace('type="SETATEY"', 'type="SET"')
    decoded_preds = decoded_preds.replace('type="SETATE"', 'type="SET"')
    decoded_preds = decoded_preds.replace('type="DATEATE"', 'type="DATE"')
    decoded_preds = decoded_preds.replace('type="2018ATE"', 'type="DATE"')
    decoded_preds = decoded_preds.replace('type="SETURATION"', 'type="DURATION"')
    decoded_preds = decoded_preds.replace('type="SETATEATION"', 'type="SET"')
    decoded_preds = decoded_preds.replace('type="SETSETY"', 'type="SET"')
    decoded_preds = decoded_preds.replace('fre="SET"', 'type="SET"')
    decoded_preds = decoded_preds.replace('fre="D"', 'type="DATE"')
    decoded_preds = decoded_preds.replace('type="2014ATE"', 'type="DATE"')
    decoded_preds = decoded_preds.replace('quan = " set "', 'type="SET"')
    decoded_preds = decoded_preds.replace('quant="D"', 'type="DATE"')
    decoded_preds = decoded_preds.replace('quan=" duration "', 'type="DURATION"')
    decoded_preds = decoded_preds.replace('quan = " duration "', 'type="DURATION"')
    decoded_preds = decoded_preds.replace('fr=" date "', 'type="DATE"')
    decoded_preds = decoded_preds.replace('nowENT', 'now"')
    decoded_preds = decoded_preds.replace('WeekEND', 'Weekends"')
    decoded_preds = decoded_preds.replace('yesterdayENT', 'yesterday"')
    decoded_preds = decoded_preds.replace('yesterdayXX', 'yesterday"')
    decoded_preds = decoded_preds.replace('type = "date"', 'type="DATE"')
    decoded_preds = decoded_preds.replace('type = " date "', 'type="DATE"')
    decoded_preds = decoded_preds.replace('type = "set"', 'type="SET"')
    decoded_preds = decoded_preds.replace('type = " set "', 'type="SET"')
    decoded_preds = decoded_preds.replace('type = " duration "', 'type="DURATION"')
    decoded_preds = decoded_preds.replace('type = "duration"', 'type="DURATION"')
    decoded_preds = decoded_preds.replace('type = "time"', 'type="TIME"')
    decoded_preds = decoded_preds.replace('type = " time "', 'type="TIME"')
    decoded_preds = decoded_preds.replace('type = "setate"', 'type="SET"')
    decoded_preds = decoded_preds.replace('type="SETVERY"', 'type="SET"')
    decoded_preds = decoded_preds.replace('type=""', 'type="DATE"')
    decoded_preds = decoded_preds.replace('quant="SET"', 'type="SET""')
    decoded_preds = decoded_preds.replace('fr = " set "', 'type="SET""')
    decoded_preds = decoded_preds.replace('fre="D" "', 'type="DATE""')
    decoded_preds = decoded_preds.replace('2014timex3', '2014</timex3>')
    decoded_preds = decoded_preds.replace('yesterdayterday', 'yesterday')
    decoded_preds = decoded_preds.replace('tomorrowENT', 'tomorrow')
    decoded_preds = decoded_preds.replace('tomorroworrow', 'tomorrow')
    decoded_preds = decoded_preds.replace('tomorrowXX', 'tomorrow')
    decoded_preds = decoded_preds.replace('todayorrow', 'tomorrow')
    decoded_preds = decoded_preds.replace('summermer', 'summer')
    decoded_preds = decoded_preds.replace('summerUT', 'summer')
    decoded_preds = decoded_preds.replace('summerSU', 'summer')
    decoded_preds = decoded_preds.replace('tomXX', 'tomorrow')
    decoded_preds = decoded_preds.replace('tom60', 'tomorrow')
    decoded_preds = re.sub('<timex3>', '</timex3>', decoded_preds)
    decoded_preds = decoded_preds.replace('<timex3 > = " date "', '<timex3  type="DATE"')
    decoded_preds = decoded_preds.replace('<timex3> = " date "', '<timex3  type="DATE"')
    decoded_preds = decoded_preds.replace('quan=" duration "', 'type="DURATION"')
    decoded_preds = decoded_preds.replace('fr =" date "', 'type="DATE"')
    decoded_preds = decoded_preds.replace('fr = " date "', 'type="DATE"')

    # some more tag formating
    decoded_preds = decoded_preds.replace(':">">">', '')
    decoded_preds = decoded_preds.replace('>>', '>')
    decoded_preds = decoded_preds.replace('":">', '">')
    decoded_preds = decoded_preds.replace('P3:">:">-', 'P3')
    decoded_preds = decoded_preds.replace('</ ', '')
    decoded_preds = re.sub(r"\"\>[\w\:\-]+\"\>", '">', decoded_preds)
    decoded_preds = re.sub(r"\<\/[\w\-\:]+\<\/", '</', decoded_preds)
    decoded_preds = re.sub(r"\"\>XX\-", '">', decoded_preds)
    decoded_preds = re.sub(r'\">:\">', '">', decoded_preds)
    decoded_preds = re.sub(r':timex3>.', '</timex3>', decoded_preds)
    decoded_preds = re.sub('\w+timex3\stype', '<timex3 type', decoded_preds)
    decoded_preds = re.sub('\d+timex3\stype', '<timex3 type', decoded_preds)
    decoded_preds = re.sub('<timex3>', '</timex3>', decoded_preds)
    decoded_preds = re.sub('--timex3>', '</timex3>', decoded_preds)
    decoded_preds = decoded_preds.replace('<timex3> = " date "', '<timex3  type="DATE"')
    truncated_values = re.findall(r'value=\"[\w\-\:]+\s', decoded_preds)
    for v in truncated_values:
        decoded_preds = decoded_preds.replace(v, v + '">')

    concatanated_value = re.findall(r'\w+\-timex3\>', decoded_preds)
    for v in concatanated_value:
        decoded_preds = decoded_preds.replace(v, v.split("-")[0] + '"<' + v.split("-")[1])

    additional_white_space = re.findall(r'value=\"[\d\w\:\-\_]+\s\"', decoded_preds)
    for v in additional_white_space:
        decoded_preds = decoded_preds.replace(v, v.replace(" ", ""))

    double_end = re.findall(r'\"\>[\w]+\"\>', decoded_preds)
    for v in double_end:
        decoded_preds = decoded_preds.replace(v, v[2:])

    strange_values = re.findall(r'\"\:\"\>', decoded_preds)
    for v in strange_values:
        decoded_preds = decoded_preds.replace(v, '">')

    decoded_preds = re.sub(r' <\n', '\n', decoded_preds)
    decoded_preds = re.sub(r'  ', ' ', decoded_preds)

    decoded_preds = re.sub(r'\b(\w+)( \1\b)+', r'\1', decoded_preds)


    return decoded_preds


if __name__ == "__main__":

    args = get_args()
    model_type = args.model_type
    padding = "max_length"
    overwrite_cache = False
    folder_name = args.model_path
    if model_type == "bert":
        tokenizer = BertTokenizerFast.from_pretrained("bert-base-uncased")
    else:
        tokenizer = RobertaTokenizerFast.from_pretrained("roberta-base")
    tokenizer.bos_token = tokenizer.cls_token
    tokenizer.eos_token = tokenizer.sep_token

    model = EncoderDecoderModel.from_pretrained(folder_name)

    # set special tokens
    model.config.decoder_start_token_id = tokenizer.bos_token_id
    model.config.eos_token_id = tokenizer.eos_token_id
    model.config.pad_token_id = tokenizer.pad_token_id

    # sensible parameters for beam search
    model.config.vocab_size = model.config.decoder.vocab_size
    model.config.max_length = args.max_length
    model.config.min_length = args.min_length
    model.config.no_repeat_ngram_size = args.no_repeat_ngram_size
    model.config.early_stopping = args.early_stopping
    model.config.length_penalty = args.length_penalty
    model.config.num_beams = args.num_beams

    os.makedirs(args.output_dir, exist_ok=True)
    model.eval()
    json_file = []
    data_files = {}
    print("dataset_type:", args.dataset_type)
    for fn in tqdm(sorted(os.listdir(args.input_dir))):
        # Only process files with the correct extension
        if fn.endswith(args.file_ext):
            input_text, output_text, beginning, end, all_text = process_file(os.path.join(args.input_dir, fn),
                                                                             args.dataset_type)
            model_inputs = tokenizer(input_text, max_length=args.max_length, padding=padding, truncation=True,
                                     return_tensors="pt")
            model_label = tokenizer(output_text, max_length=args.max_length, padding=padding, truncation=True,
                                    return_tensors="pt")
            mask = [
                [(l if l != tokenizer.pad_token_id else -100) for l in label] for label in model_label["input_ids"]
            ]
            model_inputs["decoder_input_ids"] = model_label.input_ids

            model_inputs["decoder_attention_mask"] = model_label.attention_mask

            with torch.no_grad():
                outputs = model(**model_inputs)
                predictions = outputs.logits
            preds = predictions.argmax(-1)  # greedy decoding
            preds = np.where(np.array(mask) != -100, preds, tokenizer.pad_token_id)
            # generate the predictions and decode them
            decoded_preds = tokenizer.batch_decode(preds,skip_special_tokens=True)
            # paragraph splitting is different for wikiwars
            split_on = "\n" if args.dataset_type == "wikiwars" else "\n\n"
            decoded_preds = split_on.join(decoded_preds)
            if args.dataset_type == "wikiwars":
                decoded_preds = "\n" + decoded_preds

            # clean the predictions.
            decoded_preds = clean_predictions(decoded_preds)
            if all_text.startswith("\n\n"):
                decoded_preds = "\n\n" + decoded_preds
            elif all_text.startswith("\n"):
                decoded_preds = "\n" + decoded_preds

            new_paragraphs = []
            index = 0

            for paragraph, original_para in zip(decoded_preds.split(split_on), all_text.split(split_on)):
                # bert lower casess everything, so we need to do the same to find the matches
                original_parag_lower = original_para.lower()
                if args.model_type == "bert":
                    original_paragraph = original_parag_lower
                else:
                    original_paragraph = original_para

                end_previous_timex = 0
                new_text = ""
                pred_soup = BeautifulSoup(paragraph, "lxml")
                timex_preds = pred_soup.findAll("timex3")

                previous_timex_cleaned_text = ""
                for timex in timex_preds:
                    cleaned_text = timex.text.replace("<", "").replace(">", "").replace("\"", "").strip()

                    # sometimes the cleaninng has leftovers
                    if cleaned_text.startswith("- "):
                        cleaned_text = cleaned_text[2:]

                    if len(cleaned_text) < 2 or cleaned_text in ["Yesterday", "BP", "regularly", "t.", "11",
                                                                 "the same time in", "'s", "becoming", "at"]:
                        continue;
                    beginning_timex = original_paragraph[end_previous_timex:].find(cleaned_text)
                    if cleaned_text == "day" and beginning_timex != -1 and original_paragraph[
                                                                           beginning_timex - 2:beginning_timex] == "to":
                        cleaned_text = "today"
                        beginning_timex = original_paragraph[end_previous_timex:].find(cleaned_text)
                    # if the model predicted full year instead of the last two digits
                    if beginning_timex == -1 and len(cleaned_text) == 4 and cleaned_text.isdigit():
                        beginning_timex = original_paragraph[end_previous_timex:].find(cleaned_text[2:])
                        cleaned_text = cleaned_text[2:].strip()

                    # if the model predicted full year with an extra repeation
                    if beginning_timex == -1 and len(cleaned_text) == 6 and cleaned_text.isdigit():
                        beginning_timex = original_paragraph[end_previous_timex:].find(cleaned_text[:-2])
                        cleaned_text = cleaned_text[:-2].strip()

                    # if the first word is repeating
                    elif beginning_timex == -1 and len(cleaned_text.split(" ")) > 1 and cleaned_text.split(" ")[0] == \
                            cleaned_text.split(" ")[1]:
                        cleaned_text = ' '.join(cleaned_text.split(" ")[:-1])
                        beginning_timex = original_paragraph[end_previous_timex:].find(cleaned_text)

                    # if the first and last word is repeating
                    elif beginning_timex == -1 and len(cleaned_text.split(" ")) > 1 and cleaned_text.split(" ")[0] == \
                            cleaned_text.split(" ")[-1]:
                        cleaned_text = ' '.join(cleaned_text.split(" ")[1:])
                        beginning_timex = original_paragraph[end_previous_timex:].find(cleaned_text)
                    # if its single word separated by "-"
                    elif beginning_timex == -1 and len(cleaned_text.split(" ")) < 2 and len(
                            cleaned_text.split("-")) > 1:
                        for word in cleaned_text.split("-"):
                            if word in original_paragraph[end_previous_timex:]:
                                cleaned_text = word
                                beginning_timex = original_paragraph[end_previous_timex:].find(cleaned_text)
                                break;
                    # more than one words the first one is a digit
                    elif beginning_timex == -1 and len(cleaned_text.split(" ")) < 2 and len(cleaned_text) > 2 and \
                            not cleaned_text[:1].isdigit() and cleaned_text[-1].isdigit():
                        word = cleaned_text[:-1]
                        if word.lower() in original_paragraph[end_previous_timex:].lower():
                            cleaned_text = word
                            beginning_timex = original_paragraph[end_previous_timex:].lower().find(cleaned_text.lower())
                            break

                    # if its just a single word
                    elif beginning_timex == -1 and len(cleaned_text.split(" ")) < 2 and len(cleaned_text) > 2 and \
                            not cleaned_text[0].isdigit() and cleaned_text[-1].isdigit():
                        for i in range(2, len(cleaned_text)):
                            word = cleaned_text[:i]
                            if " " + word + " " in original_paragraph[end_previous_timex:] or \
                                    " " + word + "." in original_paragraph[end_previous_timex:] or \
                                    " " + word + "," in original_paragraph[end_previous_timex:]:
                                cleaned_text = word
                                beginning_timex = original_paragraph[end_previous_timex:].find(cleaned_text)
                                break

                    # if its just a single word ending with digits
                    if beginning_timex == -1 and len(cleaned_text.split(" ")) < 2:
                        for i in range(2, len(cleaned_text)):
                            word = cleaned_text[:i]
                            if " " + word + " " in original_paragraph[end_previous_timex:] or \
                                    " " + word + "." in original_paragraph[end_previous_timex:] or \
                                    " " + word + "," in original_paragraph[end_previous_timex:]:
                                cleaned_text = word
                                beginning_timex = original_paragraph[end_previous_timex:].find(cleaned_text)
                                break
                    # if you can not find it, see if you can match the first word in the multi word one
                    if beginning_timex == -1 and len(cleaned_text.split(" ")) > 1:
                        for word in cleaned_text.split(" "):
                            if word in original_paragraph[end_previous_timex:] and word not in ["a", "-", ".", "the",
                                                                                                "in", "then", "'s",
                                                                                                "have", "at", "be"]:
                                cleaned_text = word
                                beginning_timex = original_paragraph[end_previous_timex:].find(cleaned_text)
                                break

                    if beginning_timex == -1 and cleaned_text.lower() in original_paragraph[
                                                                         end_previous_timex:].lower():
                        beginning_timex = original_paragraph[end_previous_timex:].lower().find(cleaned_text.lower())

                    # avoid tag repetion
                    if cleaned_text == previous_timex_cleaned_text:
                        continue

                    previous_timex_cleaned_text = cleaned_text

                    if beginning_timex == -1:  # if you still do not find a match, just forget it.
                        continue

                    index = index + 1
                    beginning_timex = beginning_timex + end_previous_timex
                    # if the word ended with one of these symbols do not put a space after timex tag
                    if original_paragraph[beginning_timex - 1:beginning_timex] in ["\n", "'", "-", ",", "\"",
                                                                                   "("] or original_paragraph[
                                                                                           beginning_timex - 1:beginning_timex].isdigit():
                        new_text += f'{original_para[end_previous_timex:beginning_timex]}<TIMEX3 tid="t{index + 1}" ' \
                                    f'type="{timex.attrs["type"].upper()}" ' \
                                    f'value="{timex.attrs["value"].strip().replace("</timex3>", "").replace("<", "").replace(">", "").replace(" ", "").upper()}">{original_para[beginning_timex:beginning_timex + len(cleaned_text)]}' \
                                    f'</TIMEX3>'

                    else:  # otherwises put a space
                        new_text += f'{original_para[end_previous_timex:beginning_timex]} <TIMEX3 tid="t{index + 1}" ' \
                                    f'type="{timex.attrs["type"].upper()}" ' \
                                    f'value="{timex.attrs["value"].strip().replace("</timex3>", "").replace("<", "").replace(">", "").replace(" ", "").upper()}">{original_para[beginning_timex:beginning_timex + len(cleaned_text)]}' \
                                    f'</TIMEX3>'

                    end_previous_timex = beginning_timex + len(cleaned_text)

                new_text = new_text + original_para[end_previous_timex:]
                new_text = new_text.replace("  ", " ")
                new_text = new_text.replace("\n ", "\n")
                if new_text.startswith(" "):
                    new_text = new_text[1:]
                new_paragraphs.append(new_text)

            # combine the paragraphs based on the document type and add the header and footers
            if args.dataset_type == "tempeval":
                combined_out = "\n\n".join(new_paragraphs)
            else:
                combined_out = "\n".join(new_paragraphs)
            combined_out = beginning + combined_out + end
            if args.dataset_type != "tweets":
                combined_out = re.sub(r"<TEXT>\n([A-Za-z<])", "<TEXT>\n\n\g<1>", combined_out)
            else:
                combined_out = combined_out.replace("\n\n", "\n")
            with open(os.path.join(args.output_dir, fn), "w") as f:
                f.write(combined_out)
