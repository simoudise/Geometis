from rdflib import Namespace

# Define the UKO namespace - using local URN
UKO = Namespace("urn:urban-kg:")

# =============================================================================
# ENHANCED VERSION v2.0: Comprehensive transportation infrastructure mapping
# =============================================================================
# Updates:
# - Added vulnerable population facility mappings
# - Added neighborhood/district type mappings  
# - Added safety infrastructure mappings
# - Added ADAS-relevant traffic control mappings
# =============================================================================

OSM_UKO_MAPPER = {
    "shop": {
        "supermarket": UKO.Supermarket,
        "convenience": UKO.ConvenienceStore,
        "department_store": UKO.DepartmentStore,
        "mall": UKO.ShoppingCenter,
        "clothes": UKO.ClothingStore,
        "shoes": UKO.ShoeStore,
        "books": UKO.Bookstore,
        "pharmacy": UKO.Pharmacy,
        "bakery": UKO.Bakery,
        "butcher": UKO.ButcherShop,
        "car": UKO.CarDealership,
        "car_repair": UKO.AutoRepairShop,
        "fuel": UKO.FuelStation,
        "hardware": UKO.HardwareStore,
        "furniture": UKO.FurnitureStore,
        "electronics": UKO.ElectronicsStore,
        "bicycle": UKO.BicycleShop,
        "sports": UKO.SportsStore,
        "gift": UKO.GiftShop,
        "jewelry": UKO.JewelryStore,
        "florist": UKO.FlowerShop,
        "pet": UKO.PetStore,
        "toys": UKO.ToyStore,
        "beauty": UKO.BeautySupplyStore,
        "hairdresser": UKO.HairSalon,
        "optician": UKO.OpticalShop,
        "mobile_phone": UKO.MobilePhoneStore,
        "computer": UKO.ComputerStore,
        "music": UKO.MusicStore,
        "video": UKO.VideoStore,
        "outdoor": UKO.OutdoorStore,
        "garden_centre": UKO.GardenCenter,
        "doityourself": UKO.HomeImprovementStore,
        "alcohol": UKO.LiquorStore,
        "wine": UKO.WineShop,
        "tobacco": UKO.TobaccoShop,
        "art": UKO.ArtSupplyStore,
        "stationery": UKO.StationeryStore,
        "travel_agency": UKO.TravelAgency,
        "laundry": UKO.Laundromat,
        "dry_cleaning": UKO.DryCleaner,
        "tattoo": UKO.TattooShop,
        "massage": UKO.MassageTherapy,
        "copyshop": UKO.CopyShop,
        "photo": UKO.PhotoShop,
        "frame": UKO.FramingShop,
        "locksmith": UKO.LocksmithShop,
        "interior_decoration": UKO.InteriorDesignStore,
        "fabric": UKO.FabricStore,
        "leather": UKO.LeatherGoodsStore,
        "variety_store": UKO.VarietyStore,
        "second_hand": UKO.ThriftStore,
        "antiques": UKO.AntiqueStore,
        "pawnbroker": UKO.PawnShop,
        "money_lender": UKO.PaydayLoanStore,
        "ticket": UKO.TicketOffice,
        "lottery": UKO.LotteryOffice,
        "games": UKO.GameStore,
        "fishing": UKO.FishingSupplyStore,
        "hunting": UKO.HuntingSupplyStore,
        "military_surplus": UKO.MilitarySurplusStore,
        "security": UKO.SecurityStore,
        "storage_rental": UKO.StorageRental,
        "vacant": UKO.VacantStore
    },
    
    "amenity": {
        # Healthcare and Medical
        "hospital": UKO.Hospital,
        "clinic": UKO.Clinic,
        "doctors": UKO.DoctorsOffice,
        "dentist": UKO.DentistOffice,
        "pharmacy": UKO.Pharmacy,
        "veterinary": UKO.VeterinaryClinic,
        
        # NEW: Vulnerable Population Facilities (from Safety Extension)
        "nursing_home": UKO.NursingHome,
        "social_facility": UKO.SocialFacility,  # Generic, will be refined by social_facility tag
        
        # Educational Institutions
        "school": UKO.School,
        "kindergarten": UKO.Kindergarten,
        "college": UKO.College,
        "university": UKO.University,
        "library": UKO.Library,
        "research_institute": UKO.ResearchInstitute,
        
        # Food and Dining
        "restaurant": UKO.Restaurant,
        "fast_food": UKO.FastFoodRestaurant,
        "cafe": UKO.Cafe,
        "pub": UKO.Pub,
        "bar": UKO.Bar,
        "food_court": UKO.FoodCourt,
        "biergarten": UKO.BeerGarden,
        "ice_cream": UKO.IceCreamParlor,
        
        # Financial Services
        "bank": UKO.Bank,
        "bureau_de_change": UKO.CurrencyExchange,
        "atm": UKO.ATM,
        "credit_union": UKO.CreditUnion,
        
        # Transportation
        "fuel": UKO.FuelStation,
        "charging_station": UKO.ChargingStation,
        "car_wash": UKO.CarWash,
        "car_rental": UKO.CarRental,
        "taxi": UKO.TaxiStand,
        "bus_station": UKO.BusStation,
        "ferry_terminal": UKO.FerryTerminal,
        "parking": UKO.ParkingFacility,
        "parking_space": UKO.ParkingSpace,
        "bicycle_parking": UKO.BicycleParking,
        "bicycle_rental": UKO.BikeRental,
        "car_sharing": UKO.CarSharing,
        
        # Entertainment and Recreation
        "theatre": UKO.Theater,
        "cinema": UKO.Cinema,
        "arts_centre": UKO.ArtsCenter,
        "nightclub": UKO.Nightclub,
        "casino": UKO.Casino,
        "community_centre": UKO.CommunityCenter,
        "social_centre": UKO.SocialCenter,
        "youth_centre": UKO.YouthCenter,
        "senior_centre": UKO.SeniorCenter,  # Maps to SeniorFacility in safety extension
        
        # Public Services
        "townhall": UKO.TownHall,
        "courthouse": UKO.Courthouse,
        "police": UKO.PoliceStation,
        "fire_station": UKO.FireStation,
        "post_office": UKO.PostOffice,
        "embassy": UKO.Embassy,
        "consulate": UKO.Consulate,
        
        # Religious
        "place_of_worship": UKO.PlaceOfWorship,
        "church": UKO.Church,
        "mosque": UKO.Mosque,
        "synagogue": UKO.Synagogue,
        "temple": UKO.Temple,
        "chapel": UKO.Chapel,
        "cathedral": UKO.Cathedral,
        "monastery": UKO.Monastery,
        
        # Accommodation
        "hotel": UKO.Hotel,
        "motel": UKO.Motel,
        "hostel": UKO.Hostel,
        "guest_house": UKO.GuestHouse,
        "bed_and_breakfast": UKO.BedAndBreakfast,
        "camp_site": UKO.Campground,
        "caravan_site": UKO.RVPark,
        
        # Utilities and Infrastructure
        "toilets": UKO.PublicToilet,
        "drinking_water": UKO.DrinkingWater,
        "fountain": UKO.Fountain,
        "waste_basket": UKO.WasteBasket,
        "recycling": UKO.RecyclingCenter,
        "waste_disposal": UKO.WasteDisposal,
        "telephone": UKO.Telephone,
        "internet_cafe": UKO.InternetCafe,
        "public_wifi": UKO.PublicWifi,
        
        # Emergency Services
        "emergency_phone": UKO.EmergencyPhone,
        "defibrillator": UKO.Defibrillator,
        "first_aid": UKO.FirstAidStation,
        
        # Sports and Fitness
        "gym": UKO.Gym,
        "fitness_centre": UKO.FitnessCenter,
        "swimming_pool": UKO.SwimmingPool,
        "spa": UKO.Spa,
        "sauna": UKO.Sauna,
        "sports_centre": UKO.SportsCenter,
        "stadium": UKO.Stadium,
        "golf_course": UKO.GolfCourse,
        "tennis": UKO.TennisCourt,
        "basketball": UKO.BasketballCourt,
        "soccer": UKO.SoccerField,
        "baseball": UKO.BaseballField,
        "american_football": UKO.FootballField,
        "ice_rink": UKO.IceRink,
        "bowling_alley": UKO.BowlingAlley,
        "climbing": UKO.ClimbingGym,
        "horse_riding": UKO.HorseRiding,
        "shooting_range": UKO.ShootingRange,
        "skateboard": UKO.SkateboardPark,
        "bmx": UKO.BMXPark,
        
        # Miscellaneous
        "marketplace": UKO.Marketplace,
        "studio": UKO.Studio,
        "workshop": UKO.Workshop,
        "coworking_space": UKO.CoworkingSpace,
        "conference_centre": UKO.ConferenceCenter,
        "exhibition_centre": UKO.ExhibitionCenter,
        "planetarium": UKO.Planetarium,
        "dive_centre": UKO.DiveCenter,
        "boat_rental": UKO.BoatRental,
        "public_bookcase": UKO.PublicBookcase,
        "vending_machine": UKO.VendingMachine,
        "shelter": UKO.Shelter,
        "hunting_stand": UKO.HuntingStand,
        "animal_shelter": UKO.AnimalShelter,
        "animal_boarding": UKO.AnimalBoarding,
        "childcare": UKO.Childcare,
    },
    
    # NEW: Social facility types (vulnerable populations)
    "social_facility": {
        "nursing_home": UKO.NursingHome,
        "assisted_living": UKO.AssistedLivingFacility,
        "group_home": UKO.GroupHome,
        "hospice": UKO.Hospice,
        "day_care": UKO.AdultDayCare,
        "ambulatory_care": UKO.AmbulatoryCareFacility,
        "outpatient": UKO.OutpatientFacility,
        "shelter": UKO.HomelessShelter,
        "food_bank": UKO.FoodBank,
        "soup_kitchen": UKO.SoupKitchen,
        "workshop": UKO.ShelteredWorkshop,
        "clothing_bank": UKO.ClothingBank,
    },
    
    # NEW: Social facility "for" attribute (who the facility serves)
    "social_facility:for": {
        "senior": UKO.SeniorFacility,
        "elderly": UKO.SeniorFacility,
        "disabled": UKO.DisabilityFacility,
        "mental_health": UKO.MentalHealthFacility,
        "homeless": UKO.HomelessFacility,
        "child": UKO.ChildFacility,
        "juvenile": UKO.JuvenileFacility,
        "underprivileged": UKO.UnderprivilegedFacility,
        "refugee": UKO.RefugeeFacility,
        "migrant": UKO.MigrantFacility,
        "victim": UKO.VictimSupportFacility,
        "abused": UKO.AbuseVictimFacility,
        "drug_addicted": UKO.DrugRehabFacility,
        "diseased": UKO.DiseaseSupportFacility,
    },
    
    # Healthcare facilities (more specific)
    "healthcare": {
        "hospital": UKO.Hospital,
        "clinic": UKO.Clinic,
        "doctor": UKO.DoctorsOffice,
        "doctors": UKO.DoctorsOffice,
        "dentist": UKO.DentistOffice,
        "pharmacy": UKO.Pharmacy,
        "physiotherapist": UKO.Physiotherapist,
        "psychotherapist": UKO.Psychotherapist,
        "optometrist": UKO.Optometrist,
        "podiatrist": UKO.Podiatrist,
        "speech_therapist": UKO.SpeechTherapist,
        "occupational_therapist": UKO.OccupationalTherapist,
        "rehabilitation": UKO.RehabilitationCenter,
        "nursing_home": UKO.NursingHome,
        "hospice": UKO.Hospice,
        "blood_donation": UKO.BloodDonationCenter,
        "birthing_center": UKO.BirthingCenter,
        "dialysis": UKO.DialysisCenter,
        "laboratory": UKO.MedicalLaboratory,
        "alternative": UKO.AlternativeMedicine,
        "audiologist": UKO.Audiologist,
        "centre": UKO.MedicalCenter,
        "midwife": UKO.MidwifeOffice,
        "nurse": UKO.NursingClinic,
        "sample_collection": UKO.SampleCollectionCenter,
        "vaccination_centre": UKO.VaccinationCenter,
    },
    
    # Highway and road infrastructure
    "highway": {
        # Road types
        "motorway": UKO.Motorway,
        "trunk": UKO.TrunkRoad,
        "primary": UKO.PrimaryRoad,
        "secondary": UKO.SecondaryRoad,
        "tertiary": UKO.TertiaryRoad,
        "unclassified": UKO.UnclassifiedRoad,
        "residential": UKO.ResidentialRoad,
        "service": UKO.ServiceRoad,
        "living_street": UKO.LivingStreet,
        "pedestrian": UKO.PedestrianStreet,
        "track": UKO.Track,
        "bus_guideway": UKO.BusGuideway,
        "raceway": UKO.Raceway,
        "road": UKO.Road,
        
        # Links
        "motorway_link": UKO.MotorwayLink,
        "trunk_link": UKO.TrunkLink,
        "primary_link": UKO.PrimaryLink,
        "secondary_link": UKO.SecondaryLink,
        "tertiary_link": UKO.TertiaryLink,
        
        # Active mobility infrastructure
        "footway": UKO.Footway,
        "cycleway": UKO.Cycleway,
        "bridleway": UKO.BridleWay,
        "steps": UKO.Steps,
        "path": UKO.Path,
        "sidewalk": UKO.Sidewalk,
        
        # Crossings (important for safety)
        "crossing": UKO.PedestrianCrossing,
        "traffic_signals": UKO.TrafficSignal,
        "stop": UKO.StopSign,
        "give_way": UKO.YieldSign,
        
        # Traffic calming (safety infrastructure)
        "speed_bump": UKO.SpeedBump,
        "speed_hump": UKO.SpeedHump,
        "speed_table": UKO.SpeedTable,
        "chicane": UKO.Chicane,
        "choker": UKO.Choker,
        "island": UKO.TrafficIsland,
        "mini_roundabout": UKO.MiniRoundabout,
        
        # Other infrastructure
        "bus_stop": UKO.BusStop,
        "platform": UKO.Platform,
        "turning_circle": UKO.TurningCircle,
        "turning_loop": UKO.TurningLoop,
        "street_lamp": UKO.StreetLamp,
        "milestone": UKO.Milestone,
        "passing_place": UKO.PassingPlace,
        "rest_area": UKO.RestArea,
        "services": UKO.HighwayServices,
        "emergency_access_point": UKO.EmergencyAccessPoint,
        "emergency_bay": UKO.EmergencyBay,
        "toll_gantry": UKO.TollGantry,
    },
    
    # NEW: Traffic calming (explicit mapping)
    "traffic_calming": {
        "bump": UKO.SpeedBump,
        "hump": UKO.SpeedHump,
        "table": UKO.SpeedTable,
        "cushion": UKO.SpeedCushion,
        "chicane": UKO.Chicane,
        "choker": UKO.Choker,
        "island": UKO.TrafficIsland,
        "mini_roundabout": UKO.MiniRoundabout,
        "rumble_strip": UKO.RumbleStrip,
        "dip": UKO.TrafficDip,
        "yes": UKO.TrafficCalming,
    },
    
    # NEW: Crossing types (safety-critical)
    "crossing": {
        "traffic_signals": UKO.SignalizedCrossing,
        "uncontrolled": UKO.UncontrolledCrossing,
        "marked": UKO.MarkedCrossing,
        "unmarked": UKO.UnmarkedCrossing,
        "zebra": UKO.ZebraCrossing,
        "pelican": UKO.PelicanCrossing,
        "puffin": UKO.PuffinCrossing,
        "toucan": UKO.ToucanCrossing,
        "pegasus": UKO.PegasusCrossing,
        "island": UKO.CrossingIsland,
    },
    
    # Bicycle infrastructure
    "cycleway": {
        "lane": UKO.UnprotectedBikeLane,
        "track": UKO.ProtectedBikeLane,
        "opposite": UKO.ContraflowBikeLane,
        "opposite_lane": UKO.ContraflowBikeLane,
        "shared_lane": UKO.SharedBikeLane,
        "share_busway": UKO.SharedBusBikeLane,
        "crossing": UKO.BicycleCrossing,
        "asl": UKO.AdvancedStopLine,  # Bike box
    },
    
    # Sidewalk infrastructure
    "sidewalk": {
        "both": UKO.SidewalkBothSides,
        "left": UKO.SidewalkLeft,
        "right": UKO.SidewalkRight,
        "none": UKO.NoSidewalk,
        "separate": UKO.SeparateSidewalk,
    },
    
    # Footway types
    "footway": {
        "sidewalk": UKO.Sidewalk,
        "crossing": UKO.PedestrianCrossing,
        "link": UKO.FootwayLink,
        "access_aisle": UKO.AccessAisle,
        "traffic_island": UKO.PedestrianIsland,
    },
    
    # Leisure facilities
    "leisure": {
        "park": UKO.Park,
        "playground": UKO.Playground,
        "garden": UKO.Garden,
        "nature_reserve": UKO.NatureReserve,
        "sports_centre": UKO.SportsCenter,
        "swimming_pool": UKO.SwimmingPool,
        "fitness_centre": UKO.FitnessCenter,
        "stadium": UKO.Stadium,
        "pitch": UKO.SportsPitch,
        "track": UKO.RunningTrack,
        "golf_course": UKO.GolfCourse,
        "miniature_golf": UKO.MiniatureGolf,
        "water_park": UKO.WaterPark,
        "marina": UKO.Marina,
        "slipway": UKO.BoatLaunch,
        "beach_resort": UKO.BeachResort,
        "picnic_table": UKO.PicnicArea,
        "firepit": UKO.FirePit,
        "fishing": UKO.FishingArea,
        "bird_hide": UKO.BirdHide,
        "dog_park": UKO.DogPark,
        "disc_golf_course": UKO.DiscGolfCourse,
        "horse_riding": UKO.HorseRidingFacility,
        "ice_rink": UKO.IceRink,
        "hackerspace": UKO.Hackerspace,
        "dance": UKO.DanceHall,
        "bandstand": UKO.Bandstand,
        "bleachers": UKO.Bleachers,
        "outdoor_seating": UKO.OutdoorSeating,
    },
    
    # Natural features
    "natural": {
        "water": UKO.WaterBody,
        "wetland": UKO.Wetland,
        "bay": UKO.Bay,
        "beach": UKO.Beach,
        "coastline": UKO.Coastline,
        "spring": UKO.Spring,
        "hot_spring": UKO.HotSpring,
        "geyser": UKO.Geyser,
        "volcano": UKO.Volcano,
        "peak": UKO.Peak,
        "saddle": UKO.Saddle,
        "ridge": UKO.Ridge,
        "cliff": UKO.Cliff,
        "rock": UKO.Rock,
        "stone": UKO.Stone,
        "cave_entrance": UKO.CaveEntrance,
        "sinkhole": UKO.Sinkhole,
        "wood": UKO.Wood,
        "tree": UKO.Tree,
        "tree_row": UKO.TreeRow,
        "scrub": UKO.Scrub,
        "heath": UKO.Heath,
        "grassland": UKO.Grassland,
        "fell": UKO.Fell,
        "bare_rock": UKO.BareRock,
        "scree": UKO.Scree,
        "sand": UKO.Sand,
        "mud": UKO.Mud,
        "glacier": UKO.Glacier,
    },
    
    # Waterway features
    "waterway": {
        "river": UKO.River,
        "stream": UKO.Stream,
        "canal": UKO.Canal,
        "drain": UKO.Drain,
        "ditch": UKO.Ditch,
        "dock": UKO.Dock,
        "boatyard": UKO.Boatyard,
        "dam": UKO.Dam,
        "weir": UKO.Weir,
        "waterfall": UKO.Waterfall,
        "lock_gate": UKO.LockGate,
        "rapids": UKO.Rapids,
        "turning_point": UKO.TurningPoint,
        "water_point": UKO.WaterPoint,
        "fuel": UKO.MarineFuel,
    },
    
    # Building types
    "building": {
        "yes": UKO.Building,
        "house": UKO.House,
        "detached": UKO.DetachedHouse,
        "residential": UKO.ResidentialBuilding,
        "apartments": UKO.ApartmentBuilding,
        "terrace": UKO.TerraceHouse,
        "semidetached_house": UKO.SemiDetachedHouse,
        "bungalow": UKO.Bungalow,
        "dormitory": UKO.Dormitory,
        "commercial": UKO.CommercialBuilding,
        "office": UKO.OfficeBuilding,
        "industrial": UKO.IndustrialBuilding,
        "retail": UKO.RetailBuilding,
        "warehouse": UKO.Warehouse,
        "kiosk": UKO.Kiosk,
        "cabin": UKO.Cabin,
        "farm": UKO.FarmBuilding,
        "barn": UKO.Barn,
        "greenhouse": UKO.Greenhouse,
        "stable": UKO.Stable,
        "sty": UKO.Sty,
        "cowshed": UKO.Cowshed,
        "farm_auxiliary": UKO.FarmAuxiliaryBuilding,
        "shed": UKO.Shed,
        "garage": UKO.Garage,
        "garages": UKO.Garages,
        "carport": UKO.Carport,
        "parking": UKO.ParkingStructure,
        "hangar": UKO.Hangar,
        "hut": UKO.Hut,
        "tent": UKO.Tent,
        "static_caravan": UKO.StaticCaravan,
        "construction": UKO.ConstructionSite,
        "ruins": UKO.Ruins,
        "church": UKO.ChurchBuilding,
        "chapel": UKO.ChapelBuilding,
        "cathedral": UKO.CathedralBuilding,
        "mosque": UKO.MosqueBuilding,
        "synagogue": UKO.SynagogueBuilding,
        "temple": UKO.TempleBuilding,
        "shrine": UKO.ShrineBuilding,
        "monastery": UKO.MonasteryBuilding,
        "religious": UKO.ReligiousBuilding,
        "civic": UKO.CivicBuilding,
        "government": UKO.GovernmentBuilding,
        "hospital": UKO.HospitalBuilding,
        "school": UKO.SchoolBuilding,
        "university": UKO.UniversityBuilding,
        "college": UKO.CollegeBuilding,
        "public": UKO.PublicBuilding,
        "transportation": UKO.TransportationBuilding,
        "train_station": UKO.TrainStationBuilding,
        "hotel": UKO.HotelBuilding,
        "castle": UKO.Castle,
        "fort": UKO.Fort,
        "tower": UKO.Tower,
        "lighthouse": UKO.Lighthouse,
        "observatory": UKO.Observatory,
        "water_tower": UKO.WaterTower,
        "silo": UKO.Silo,
        "storage_tank": UKO.StorageTank,
        "grandstand": UKO.Grandstand,
        "pavilion": UKO.Pavilion,
        "sports_hall": UKO.SportsHall,
        "stadium": UKO.StadiumBuilding,
        "riding_hall": UKO.RidingHall,
        "boathouse": UKO.Boathouse,
        "beach_hut": UKO.BeachHut,
        "fire_station": UKO.FireStationBuilding,
        "kindergarten": UKO.KindergartenBuilding,
        "library": UKO.LibraryBuilding,
        "theatre": UKO.TheaterBuilding,
        "cinema": UKO.CinemaBuilding,
        "museum": UKO.MuseumBuilding,
        "exhibition_hall": UKO.ExhibitionHallBuilding,
        "conference_centre": UKO.ConferenceCenterBuilding,
        "community_centre": UKO.CommunityCenterBuilding,
        "social_centre": UKO.SocialCenterBuilding,
        "youth_centre": UKO.YouthCenterBuilding,
        "senior_centre": UKO.SeniorCenterBuilding,
        "amenity": UKO.AmenityBuilding,
        "supermarket": UKO.SupermarketBuilding,
        "toilets": UKO.ToiletBuilding,
        "transformer_tower": UKO.TransformerTower,
        "telephone_exchange": UKO.TelephoneExchange,
        "data_center": UKO.DataCenter,
        "cooling_tower": UKO.CoolingTower,
        "pumping_station": UKO.PumpingStation,
        "water_works": UKO.WaterWorks,
        "wastewater_plant": UKO.WastewaterTreatmentPlant,
        "waste_management": UKO.WasteManagementBuilding,
        "recycling_plant": UKO.RecyclingPlant,
        "power_substation": UKO.PowerSubstation,
        "gatehouse": UKO.Gatehouse,
        "guardhouse": UKO.Guardhouse,
        "toll_booth": UKO.TollBooth,
        "weighbridge": UKO.WeighbridgeBuilding,
        "fuel": UKO.FuelStationBuilding
    },
    
    # Land use
    "landuse": {
        "residential": UKO.ResidentialArea,
        "commercial": UKO.CommercialArea,
        "industrial": UKO.IndustrialArea,
        "retail": UKO.RetailArea,
        "institutional": UKO.InstitutionalArea,
        "recreation_ground": UKO.RecreationArea,
        "village_green": UKO.VillageGreen,
        "forest": UKO.Forest,
        "meadow": UKO.Meadow,
        "grass": UKO.GrassArea,
        "orchard": UKO.Orchard,
        "vineyard": UKO.Vineyard,
        "farmland": UKO.Farmland,
        "farmyard": UKO.Farmyard,
        "cemetery": UKO.Cemetery,
        "military": UKO.MilitaryArea,
        "quarry": UKO.Quarry,
        "landfill": UKO.Landfill,
        "brownfield": UKO.BrownfieldSite,
        "greenfield": UKO.GreenfieldSite,
        "construction": UKO.ConstructionArea,
        "railway": UKO.RailwayArea,
        "port": UKO.PortArea,
        "depot": UKO.DepotArea,
        "garages": UKO.GarageArea,
        "basin": UKO.Basin,
        "reservoir": UKO.Reservoir,
        "salt_pond": UKO.SaltPond,
        "winter_sports": UKO.WinterSportsArea,
        "allotments": UKO.CommunityGarden,
        "greenhouse_horticulture": UKO.GreenhouseArea,
        "plant_nursery": UKO.PlantNursery,
        "aquaculture": UKO.Aquaculture,
        "flowerbed": UKO.Flowerbed,
        "education": UKO.EducationalArea,
        "religious": UKO.ReligiousArea
    },
    
    # Educational infrastructure
    "preschool": {
        "kindergarten": UKO.Kindergarten,
        "nursery": UKO.Nursery,
        "childcare": UKO.Childcare,
        "daycare": UKO.Daycare,
        "preschool": UKO.Preschool,
        "early_childhood_center": UKO.EarlyChildhoodCenter,
        "family_daycare": UKO.FamilyDaycare,
        "head_start": UKO.HeadStart,
        "montessori": UKO.MontessoriSchool,
        "waldorf": UKO.WaldorfSchool,
        "play_group": UKO.PlayGroup,
        "parent_child_center": UKO.ParentChildCenter,
        "special_needs_preschool": UKO.SpecialNeedsPreschool
    },
    
    # Public transportation
    "public_transport": {
        "platform": UKO.Platform,
        "stop_area": UKO.StopArea,
        "stop_position": UKO.StopPosition,
        "station": UKO.TransitStation,
        "terminal": UKO.Terminal,
        "halt": UKO.Halt,
        "tram_stop": UKO.TramStop,
        "bus_stop": UKO.BusStop,
        "trolleybus_stop": UKO.TrolleybusStop,
        "subway_entrance": UKO.SubwayEntrance,
        "train_station_entrance": UKO.TrainStationEntrance,
        "ferry_terminal": UKO.FerryTerminal,
        "aerialway_station": UKO.AerialwayStation,
        "monorail_station": UKO.MonorailStation,
        "light_rail_station": UKO.LightRailStation,
        "subway_station": UKO.SubwayStation,
        "rail_station": UKO.RailStation,
        "bus_station": UKO.BusStation,
        "coach_station": UKO.CoachStation,
        "taxi_stand": UKO.TaxiStand,
        "bicycle_rental": UKO.BikeRental,
        "car_sharing": UKO.CarSharing,
        "park_and_ride": UKO.ParkAndRide,
        "kiss_and_ride": UKO.KissAndRide,
        "park_and_fly": UKO.ParkAndFly
    },
    
    # Geographic and administrative areas
    "place": {
        "city": UKO.City,
        "town": UKO.Town,
        "village": UKO.Village,
        "hamlet": UKO.Hamlet,
        "suburb": UKO.Suburb,
        "neighbourhood": UKO.Neighborhood,
        "quarter": UKO.Quarter,
        "district": UKO.District,
        "borough": UKO.Borough,
        "municipality": UKO.Municipality,
        "county": UKO.County,
        "state": UKO.State,
        "province": UKO.Province,
        "region": UKO.Region,
        "country": UKO.Country,
        "continent": UKO.Continent,
        "island": UKO.Island,
        "archipelago": UKO.Archipelago,
        "peninsula": UKO.Peninsula,
        "locality": UKO.Locality,
        "isolated_dwelling": UKO.IsolatedDwelling,
        "farm": UKO.Farm,
        "allotments": UKO.Allotments,
        "city_block": UKO.CityBlock,
        "plot": UKO.Plot,
        "square": UKO.Square,
        "residential_area": UKO.ResidentialArea
    },
    
    # Administrative boundaries
    "boundary": {
        "administrative": UKO.AdministrativeArea,
        "political": UKO.PoliticalBoundary,
        "postal_code": UKO.PostalCodeArea,
        "census": UKO.CensusArea,
        "protected_area": UKO.ProtectedArea,
        "national_park": UKO.NationalPark,
        "nature_reserve": UKO.NatureReserve,
        "maritime": UKO.MaritimeBoundary,
        "territorial_waters": UKO.TerritorialWaters,
        "economic_zone": UKO.EconomicZone,
        "customs": UKO.CustomsArea,
        "timezone": UKO.TimezoneArea,
        "statistical": UKO.StatisticalArea,
        "electoral": UKO.ElectoralDistrict,
        "judicial": UKO.JudicialDistrict,
        "police": UKO.PoliceDistrict,
        "fire": UKO.FireDistrict,
        "school": UKO.SchoolDistrict,
        "health": UKO.HealthDistrict,
        "water": UKO.WaterDistrict,
        "drainage_basin": UKO.DrainageBasin,
        "watershed": UKO.Watershed,
        "aboriginal_lands": UKO.AboriginalLands,
        "forest": UKO.ForestBoundary,
        "hazard": UKO.HazardArea,
        "flood_prone": UKO.FloodProneArea,
        "earthquake": UKO.EarthquakeZone,
        "military": UKO.MilitaryArea,
        "restricted": UKO.RestrictedArea,
        "user": UKO.UserDefinedBoundary
    },
    
    # Railway infrastructure
    "railway": {
        "rail": UKO.Railway,
        "subway": UKO.SubwayLine,
        "light_rail": UKO.LightRailLine,
        "tram": UKO.TramLine,
        "monorail": UKO.MonorailLine,
        "narrow_gauge": UKO.NarrowGaugeRailway,
        "miniature": UKO.MiniatureRailway,
        "funicular": UKO.FunicularRailway,
        "preserved": UKO.PreservedRailway,
        "disused": UKO.DisusedRailway,
        "abandoned": UKO.AbandonedRailway,
        "construction": UKO.RailwayConstruction,
        "proposed": UKO.ProposedRailway,
        "station": UKO.TrainStation,
        "halt": UKO.RailwayHalt,
        "platform": UKO.RailwayPlatform,
        "stop": UKO.RailwayStop,
        "tram_stop": UKO.TramStop,
        "crossing": UKO.RailwayCrossing,
        "level_crossing": UKO.LevelCrossing,
        "switch": UKO.RailwaySwitch,
        "turntable": UKO.RailwayTurntable,
        "roundhouse": UKO.Roundhouse,
        "signal": UKO.RailwaySignal,
        "buffer_stop": UKO.BufferStop,
        "traverser": UKO.RailwayTraverser,
        "wash": UKO.TrainWash,
        "yard": UKO.RailYard,
        "depot": UKO.RailwayDepot,
    },
    
    # Aeroway (airports)
    "aeroway": {
        "aerodrome": UKO.Airport,
        "runway": UKO.Runway,
        "taxiway": UKO.Taxiway,
        "apron": UKO.Apron,
        "helipad": UKO.Helipad,
        "heliport": UKO.Heliport,
        "terminal": UKO.AirportTerminal,
        "gate": UKO.AirportGate,
        "hangar": UKO.AircraftHangar,
        "windsock": UKO.Windsock,
        "navigationaid": UKO.NavigationAid,
    },
    
    # Tourism
    "tourism": {
        "hotel": UKO.Hotel,
        "motel": UKO.Motel,
        "hostel": UKO.Hostel,
        "guest_house": UKO.GuestHouse,
        "camp_site": UKO.Campground,
        "caravan_site": UKO.RVPark,
        "alpine_hut": UKO.AlpineHut,
        "wilderness_hut": UKO.WildernessHut,
        "chalet": UKO.Chalet,
        "apartment": UKO.TouristApartment,
        "attraction": UKO.TouristAttraction,
        "viewpoint": UKO.Viewpoint,
        "museum": UKO.Museum,
        "gallery": UKO.ArtGallery,
        "theme_park": UKO.ThemePark,
        "zoo": UKO.Zoo,
        "aquarium": UKO.Aquarium,
        "artwork": UKO.PublicArtwork,
        "information": UKO.TouristInformation,
        "picnic_site": UKO.PicnicSite,
    },
    
    # Historic features
    "historic": {
        "monument": UKO.Monument,
        "memorial": UKO.Memorial,
        "archaeological_site": UKO.ArchaeologicalSite,
        "ruins": UKO.HistoricRuins,
        "castle": UKO.HistoricCastle,
        "fort": UKO.HistoricFort,
        "manor": UKO.Manor,
        "battlefield": UKO.Battlefield,
        "boundary_stone": UKO.BoundaryStone,
        "milestone": UKO.HistoricMilestone,
        "wayside_cross": UKO.WaysideCross,
        "wayside_shrine": UKO.WaysideShrine,
        "city_gate": UKO.CityGate,
        "ship": UKO.HistoricShip,
        "wreck": UKO.Shipwreck,
        "aircraft": UKO.HistoricAircraft,
        "locomotive": UKO.HistoricLocomotive,
    },
}

# =============================================================================
# TAG PRIORITIES
# =============================================================================
# Higher number = higher priority when an entity has multiple matching tags

TAG_PRIORITIES = {
    "amenity": 100,           # Highest priority for business/service classification
    "healthcare": 95,         # High priority for medical facilities
    "social_facility": 93,    # NEW: High priority for vulnerable population facilities
    "shop": 90,               # High priority for retail
    "preschool": 88,          # High priority for educational institutions
    "cycleway": 85,           # HIGH priority for bicycle infrastructure
    "footway": 85,            # HIGH priority for pedestrian infrastructure
    "crossing": 84,           # NEW: High priority for safety-critical crossings
    "traffic_calming": 83,    # NEW: High priority for safety infrastructure
    "leisure": 80,            # Medium-high priority for recreation
    "tourism": 75,            # Tourism facilities
    "building": 70,           # Medium priority for building type
    "landuse": 60,            # Lower priority for land use
    "place": 50,              # Lower priority for geographic areas
    "highway": 40,            # Lower priority for transportation
    "public_transport": 30,   # Low priority
    "railway": 25,            # Railway infrastructure
    "boundary": 20,           # Lowest priority for boundaries
}

# =============================================================================
# VULNERABLE POPULATION FACILITY CLASSES
# =============================================================================
# Used by osm_handler.py for proximity relationships

VULNERABLE_POPULATION_CLASSES = {
    str(UKO.NursingHome),
    str(UKO.AssistedLivingFacility),
    str(UKO.SeniorCenter),
    str(UKO.SeniorFacility),
    str(UKO.GroupHome),
    str(UKO.Hospice),
    str(UKO.AdultDayCare),
    str(UKO.HomelessShelter),
    str(UKO.DisabilityFacility),
    str(UKO.MentalHealthFacility),
    str(UKO.ChildFacility),
    str(UKO.Daycare),
    str(UKO.Preschool),
    str(UKO.Kindergarten),
}

# =============================================================================
# SAFETY INFRASTRUCTURE CLASSES  
# =============================================================================
# Used for identifying safety-relevant features

SAFETY_INFRASTRUCTURE_CLASSES = {
    # Crossings
    str(UKO.PedestrianCrossing),
    str(UKO.SignalizedCrossing),
    str(UKO.ZebraCrossing),
    str(UKO.CrossingIsland),
    str(UKO.BicycleCrossing),
    
    # Traffic calming
    str(UKO.SpeedBump),
    str(UKO.SpeedHump),
    str(UKO.SpeedTable),
    str(UKO.Chicane),
    str(UKO.TrafficIsland),
    str(UKO.MiniRoundabout),
    str(UKO.TrafficCalming),
    
    # Signals and signs
    str(UKO.TrafficSignal),
    str(UKO.StopSign),
    str(UKO.YieldSign),
    
    # Lighting
    str(UKO.StreetLamp),
}

# =============================================================================
# NEIGHBORHOOD/DISTRICT CLASSES
# =============================================================================
# Used for area-based relationship inference

NEIGHBORHOOD_CLASSES = {
    str(UKO.Neighborhood),
    str(UKO.OfficialNeighborhood),
    str(UKO.InformalNeighborhood),
    str(UKO.HistoricNeighborhood),
    str(UKO.Suburb),
    str(UKO.Quarter),
}

DISTRICT_CLASSES = {
    str(UKO.District),
    str(UKO.FunctionalDistrict),
    str(UKO.AutoRow),
    str(UKO.RestaurantRow),
    str(UKO.ArtDistrict),
    str(UKO.EntertainmentDistrict),
    str(UKO.MedicalDistrict),
    str(UKO.DesignDistrict),
    str(UKO.TechCorridor),
    str(UKO.EthnicEnclave),
    str(UKO.Chinatown),
    str(UKO.LittleItaly),
    str(UKO.Koreatown),
}
