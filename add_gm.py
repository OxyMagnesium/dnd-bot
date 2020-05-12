import pickle

import dnd_bot

def main():
    name = input('Enter campaign to add new GM to: ')
    gm = int(input('Enter player ID to add as GM: '))

    with open(f'data/{name}', 'rb') as file:
        campaign = pickle.load(file)

    if gm not in campaign.gms:
        campaign.gms.append(gm)

    with open(f'data/{name}', 'wb') as file:
        pickle.dump(campaign, file)

    print('GM added successfully.')


if __name__ == '__main__':
    main()
